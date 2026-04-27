# Prop pricer - model distribution -> fair price -> edge vs book line
# Calibration: Platt/isotonic on 2025 closing lines
# See docs/plan.md Steps 3-4

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from eval.no_vig import NoVigMethod, remove_vig_two_sided
from models.base import StatDistribution

# ---------------------------------------------------------------------------
# American odds <-> implied probability (single-sided, includes vig in line)
# ---------------------------------------------------------------------------


def implied_prob(american: int) -> float:
    """Convert American odds to implied win probability (not vig-removed)."""
    if american < 0:
        return float(-american) / float(-american + 100)
    return 100.0 / float(american + 100)


def fair_price_to_american(p: float) -> int:
    """Map calibrated probability p in (0,1) to whole-number American odds.

    Picks a nearby integer so ``implied_prob`` round-trips within rounding error
    of discrete sportsbook lines.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be strictly between 0 and 1 for fair American odds")
    if p > 0.5:
        a0 = 100.0 * p / (1.0 - p)
        lo, hi = max(101, int(a0) - 3), int(a0) + 4
        best = min(range(lo, hi), key=lambda A: abs(implied_prob(-A) - p))
        return -best
    o0 = 100.0 * (1.0 - p) / p
    lo, hi = max(100, int(o0) - 3), int(o0) + 4
    return min(range(lo, hi), key=lambda O: abs(implied_prob(O) - p))


def edge(calibrated_prob: float, book_implied_prob: float) -> float:
    return calibrated_prob - book_implied_prob


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@dataclass
class PropCalibrator:
    """Post-hoc probability calibration: isotonic or Platt (logistic on logit)."""

    method: Literal["isotonic", "platt"] = "isotonic"
    _isotonic: IsotonicRegression | None = None
    _platt: LogisticRegression | None = None
    _fitted: bool = False

    def fit(
        self,
        raw_probs: np.ndarray,
        outcomes: np.ndarray,
    ) -> "PropCalibrator":
        """Fit on raw model probabilities and binary outcomes (1 = over hit, 0 = under)."""
        r = np.asarray(raw_probs, dtype=float).ravel()
        y = np.asarray(outcomes, dtype=float).ravel()
        if len(r) != len(y):
            raise ValueError("raw_probs and outcomes must be the same length")

        if self.method == "isotonic":
            self._isotonic = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds="clip"
            )
            self._isotonic.fit(r, y)
            self._platt = None
        else:
            eps = 1e-6
            rc = np.clip(r, eps, 1.0 - eps)
            x = np.log(rc / (1.0 - rc)).reshape(-1, 1)
            self._platt = LogisticRegression(max_iter=2000)
            self._platt.fit(x, y.astype(int))
            self._isotonic = None
        self._fitted = True
        return self

    def calibrate(
        self,
        raw: np.ndarray | float,
    ) -> np.ndarray | float:
        if not self._fitted:
            raise RuntimeError("Calibrator is not fitted")
        single = not isinstance(raw, np.ndarray)
        r = np.atleast_1d(np.asarray(raw, dtype=float))

        if self._isotonic is not None:
            out = self._isotonic.predict(r)
        else:
            assert self._platt is not None
            eps = 1e-6
            rc = np.clip(r, eps, 1.0 - eps)
            x = np.log(rc / (1.0 - rc)).reshape(-1, 1)
            out = self._platt.predict_proba(x)[:, 1]

        out = np.clip(out, 0.0, 1.0)
        if single:
            return float(out[0])
        return out

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "method": self.method,
            "isotonic": self._isotonic,
            "platt": self._platt,
            "fitted": self._fitted,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, path: Path) -> "PropCalibrator":
        data = joblib.load(Path(path))
        cal = cls(method=data.get("method", "isotonic"))
        cal._isotonic = data.get("isotonic")
        cal._platt = data.get("platt")
        cal._fitted = data.get("fitted", False)
        return cal


@dataclass(frozen=True)
class PropDecision:
    player_id: str = ""
    stat: str = ""
    line: float = float("nan")
    model_mean: float | None = None
    raw_prob_over: float = 0.0
    raw_prob_under: float = 0.0
    model_p_over_calibrated: float = 0.0
    model_p_under_calibrated: float = 0.0
    market_p_over_no_vig: float = 0.0
    market_p_under_no_vig: float = 0.0
    book_p_over_vigged: float = 0.0
    book_p_under_vigged: float = 0.0
    over_odds: int = 0
    under_odds: int = 0
    ev_over: float = 0.0
    ev_under: float = 0.0
    fair_line: float | None = None
    top_drivers: tuple[str, ...] = ()
    confidence: Literal["high", "med", "low"] = "high"
    recommendation: Literal["over", "under", "no_bet"] = "no_bet"

    def side_payload(self, side: Literal["over", "under"]) -> dict[str, float | str]:
        if side == "over":
            calibrated = self.model_p_over_calibrated
            raw = self.raw_prob_over
            odds = self.over_odds
            vigged = self.book_p_over_vigged
            no_vig = self.market_p_over_no_vig
            ev = self.ev_over
        else:
            calibrated = self.model_p_under_calibrated
            raw = self.raw_prob_under
            odds = self.under_odds
            vigged = self.book_p_under_vigged
            no_vig = self.market_p_under_no_vig
            ev = self.ev_under
        return {
            "side": side,
            "raw_prob": raw,
            "calibrated_prob": calibrated,
            "book_odds": float(odds),
            "book_implied_prob": vigged,
            "market_no_vig_prob": no_vig,
            "edge": edge(calibrated, no_vig),
            "fair_american": float(fair_price_to_american(np.clip(calibrated, 1e-6, 1.0 - 1e-6))),
            "ev": ev,
        }


# ---------------------------------------------------------------------------
# Reliability (calibration) diagram stats (+ optional figure)
# ---------------------------------------------------------------------------


def reliability_diagram(
    raw: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
    save_path: Path | None = None,
) -> dict[str, Any]:
    """Binned reliability: mean predicted vs positive rate per bin. Returns ECE among stats."""
    r = np.asarray(raw, dtype=float).ravel()
    y = np.asarray(outcomes, dtype=float).ravel()
    n = len(r)
    if n == 0:
        return {"bin_means": [], "bin_fracs": [], "ece": 0.0}

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(r, edges[1:-1], right=False)
    # digitize: 0 for < edges[1], up to n_bins-1; clamp
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    bin_means: list[float] = []
    bin_fracs: list[float] = []
    ece = 0.0
    for b in range(n_bins):
        m = bin_idx == b
        if not np.any(m):
            continue
        mean_p = float(r[m].mean())
        acc = float(y[m].mean())
        w = float(m.sum()) / n
        ece += w * abs(mean_p - acc)
        bin_means.append(mean_p)
        bin_fracs.append(acc)

    stats_out: dict[str, Any] = {
        "bin_means": bin_means,
        "bin_fracs": bin_fracs,
        "ece": ece,
    }
    if save_path is not None:
        _plot_reliability(r, y, n_bins, Path(save_path))
    return stats_out


def _plot_reliability(
    r: np.ndarray, y: np.ndarray, n_bins: int, save_path: Path
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(r, edges[1:-1], right=False)
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    xs: list[float] = []
    ys: list[float] = []
    for b in range(n_bins):
        m = bin_idx == b
        if not np.any(m):
            continue
        xs.append(float(r[m].mean()))
        ys.append(float(y[m].mean()))

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4, label="perfect")
    ax.plot(xs, ys, "o-", label="model")
    ax.set_xlabel("Mean predicted prob (bin)")
    ax.set_ylabel("Fraction positives")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Price a single over/under vs book
# ---------------------------------------------------------------------------


def price_prop(
    dist: StatDistribution,
    line: float,
    book_odds: int,
    calibrator: PropCalibrator | None,
) -> dict[str, float]:
    """P(over) from model, optional calibration, edge vs book, fair US odds."""
    raw_prob = float(dist.prob_over(line))
    if calibrator is None:
        calibrated_prob = raw_prob
    else:
        cp = calibrator.calibrate(raw_prob)
        calibrated_prob = float(cp) if not isinstance(cp, float) else cp

    book_implied = implied_prob(book_odds)
    e = edge(calibrated_prob, book_implied)
    fair_am = fair_price_to_american(calibrated_prob)
    return {
        "raw_prob": raw_prob,
        "calibrated_prob": calibrated_prob,
        "book_implied_prob": book_implied,
        "edge": e,
        "fair_american": float(fair_am),
    }


def price_two_sided_prop(
    raw_prob_over: float,
    over_odds: int,
    under_odds: int,
    calibrator: PropCalibrator | None = None,
) -> dict[str, dict[str, float | str]]:
    decision = price_two_sided_prop_decision(
        raw_prob_over=raw_prob_over,
        over_odds=over_odds,
        under_odds=under_odds,
        calibrator=calibrator,
        min_ev=0.0,
    )
    return {"over": decision.side_payload("over"), "under": decision.side_payload("under")}


def _confidence_from_inputs(inputs: dict[str, Any] | None) -> Literal["high", "low"]:
    if not inputs:
        return "high"
    for value in inputs.values():
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "low"
        if pd.isna(value):
            return "low"
    return "high"


def price_two_sided_prop_decision(
    raw_prob_over: float,
    over_odds: int,
    under_odds: int,
    calibrator: PropCalibrator | None = None,
    *,
    player_id: str = "",
    stat: str = "",
    line: float = float("nan"),
    model_mean: float | None = None,
    fair_line: float | None = None,
    top_drivers: tuple[str, ...] = (),
    inputs: dict[str, Any] | None = None,
    stake: float = 1.0,
    min_ev: float = 0.02,
    no_vig_method: NoVigMethod = "multiplicative",
) -> PropDecision:
    raw_over = float(np.clip(raw_prob_over, 0.0, 1.0))
    if calibrator is None:
        cal_over = raw_over
    else:
        cal_over = float(calibrator.calibrate(raw_over))
    cal_under = float(np.clip(1.0 - cal_over, 0.0, 1.0))
    raw_under = float(np.clip(1.0 - raw_over, 0.0, 1.0))
    market_over, market_under = remove_vig_two_sided(over_odds, under_odds, method=no_vig_method)
    over_profit = american_profit(stake, int(over_odds))
    under_profit = american_profit(stake, int(under_odds))
    ev_over = cal_over * over_profit - (1.0 - cal_over) * stake
    ev_under = cal_under * under_profit - (1.0 - cal_under) * stake
    best_side: Literal["over", "under"] = "over" if ev_over >= ev_under else "under"
    best_ev = ev_over if best_side == "over" else ev_under
    recommendation: Literal["over", "under", "no_bet"] = best_side if best_ev >= min_ev else "no_bet"

    return PropDecision(
        player_id=player_id,
        stat=stat,
        line=float(line),
        model_mean=model_mean,
        raw_prob_over=raw_over,
        raw_prob_under=raw_under,
        model_p_over_calibrated=cal_over,
        model_p_under_calibrated=cal_under,
        market_p_over_no_vig=market_over,
        market_p_under_no_vig=market_under,
        book_p_over_vigged=implied_prob(over_odds),
        book_p_under_vigged=implied_prob(under_odds),
        over_odds=int(over_odds),
        under_odds=int(under_odds),
        ev_over=float(ev_over),
        ev_under=float(ev_under),
        fair_line=fair_line,
        top_drivers=top_drivers[:3],
        confidence=_confidence_from_inputs(inputs),
        recommendation=recommendation,
    )


def american_profit(stake: float, american_odds: int) -> float:
    if american_odds < 0:
        return stake * (100.0 / abs(float(american_odds)))
    return stake * (float(american_odds) / 100.0)


def settle_pick(actual_value: float, line: float, side: str) -> str:
    if actual_value == line:
        return "push"
    if side == "over":
        return "win" if actual_value > line else "loss"
    return "win" if actual_value < line else "loss"


def build_paper_trade_picks(
    priced_rows: pd.DataFrame,
    calibrator: PropCalibrator | None = None,
    min_edge: float | None = 0.05,
    min_ev: float | None = None,
    stake: float = 1.0,
    max_picks_per_week: int | None = None,
    max_picks_per_player: int | None = None,
    max_picks_per_game: int | None = None,
    return_metadata: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, Any]]:
    candidate_rows: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {
        "input_rows": int(len(priced_rows)),
        "selected_rows": 0,
        "skipped_rows": {
            "missing_odds": 0,
            "edge_threshold": 0,
            "no_bet": 0,
            "max_picks_per_week": 0,
            "max_picks_per_player": 0,
            "max_picks_per_game": 0,
        },
    }

    for _, row in priced_rows.iterrows():
        if pd.isna(row.get("over_odds")) or pd.isna(row.get("under_odds")):
            metadata["skipped_rows"]["missing_odds"] += 1
            continue
        threshold = float(min_ev if min_ev is not None else (min_edge if min_edge is not None else 0.02))
        decision = price_two_sided_prop_decision(
            raw_prob_over=float(row["raw_prob"]),
            over_odds=int(row["over_odds"]),
            under_odds=int(row["under_odds"]),
            calibrator=calibrator,
            player_id=str(row.get("player_id", "")),
            stat=str(row.get("stat", "")),
            line=float(row.get("line", float("nan"))),
            stake=stake,
            min_ev=threshold,
            inputs=row.to_dict(),
        )
        if decision.recommendation == "no_bet":
            metadata["skipped_rows"]["edge_threshold"] += 1
            metadata["skipped_rows"]["no_bet"] += 1
            continue
        best_side = decision.side_payload(decision.recommendation)

        result = settle_pick(
            actual_value=float(row["actual_value"]),
            line=float(row["line"]),
            side=str(best_side["side"]),
        )
        profit = 0.0
        if result == "win":
            profit = american_profit(stake, int(best_side["book_odds"]))
        elif result == "loss":
            profit = -stake

        candidate_rows.append({
            "player_id": str(row["player_id"]),
            "season": int(row["season"]),
            "week": int(row["week"]),
            "stat": str(row["stat"]),
            "line": float(row["line"]),
            "actual_value": float(row["actual_value"]),
            "book": str(row["book"]) if pd.notna(row.get("book")) else "",
            "selected_side": str(best_side["side"]),
            "selected_odds": int(best_side["book_odds"]),
            "selected_book_implied_prob": float(best_side["book_implied_prob"]),
            "selected_market_no_vig_prob": float(best_side["market_no_vig_prob"]),
            "selected_fair_american": float(best_side["fair_american"]),
            "selected_raw_prob": float(best_side["raw_prob"]),
            "selected_prob": float(best_side["calibrated_prob"]),
            "selected_edge": float(best_side["edge"]),
            "selected_ev": float(best_side["ev"]),
            "model_p_over_calibrated": decision.model_p_over_calibrated,
            "model_p_under_calibrated": decision.model_p_under_calibrated,
            "market_p_over_no_vig": decision.market_p_over_no_vig,
            "market_p_under_no_vig": decision.market_p_under_no_vig,
            "ev_over": decision.ev_over,
            "ev_under": decision.ev_under,
            "recommendation": decision.recommendation,
            "confidence": decision.confidence,
            "top_drivers": list(decision.top_drivers),
            "result": result,
            "stake_units": float(stake),
            "profit_units": float(profit),
            "game_id": str(row["game_id"]) if pd.notna(row.get("game_id")) else "",
            "recent_team": str(row["recent_team"]) if pd.notna(row.get("recent_team")) else "",
            "opponent_team": str(row["opponent_team"]) if pd.notna(row.get("opponent_team")) else "",
        })

    if not candidate_rows:
        empty = pd.DataFrame(candidate_rows)
        if return_metadata:
            return empty, metadata
        return empty

    candidates = pd.DataFrame(candidate_rows).sort_values(
        ["season", "week", "selected_ev", "selected_edge", "player_id", "stat", "line"],
        ascending=[True, True, False, False, True, True, True],
    )

    selected_rows: list[dict[str, Any]] = []
    week_counts: defaultdict[tuple[int, int], int] = defaultdict(int)
    player_counts: defaultdict[tuple[int, int, str], int] = defaultdict(int)
    game_counts: defaultdict[tuple[int, int, str], int] = defaultdict(int)

    for row in candidates.to_dict("records"):
        week_key = (int(row["season"]), int(row["week"]))
        player_key = (int(row["season"]), int(row["week"]), str(row["player_id"]))
        game_id = str(row.get("game_id", ""))
        game_key = (int(row["season"]), int(row["week"]), game_id)

        if max_picks_per_week is not None and week_counts[week_key] >= max_picks_per_week:
            metadata["skipped_rows"]["max_picks_per_week"] += 1
            continue
        if max_picks_per_player is not None and player_counts[player_key] >= max_picks_per_player:
            metadata["skipped_rows"]["max_picks_per_player"] += 1
            continue
        if game_id and max_picks_per_game is not None and game_counts[game_key] >= max_picks_per_game:
            metadata["skipped_rows"]["max_picks_per_game"] += 1
            continue

        week_counts[week_key] += 1
        player_counts[player_key] += 1
        if game_id:
            game_counts[game_key] += 1
        selected_rows.append(row)

    picks = pd.DataFrame(selected_rows)
    metadata["selected_rows"] = int(len(picks))
    if return_metadata:
        return picks, metadata
    return picks


def summarize_paper_trade(picks: pd.DataFrame) -> dict[str, float]:
    if picks.empty:
        return {
            "n_bets": 0.0,
            "wins": 0.0,
            "losses": 0.0,
            "pushes": 0.0,
            "staked_units": 0.0,
            "profit_units": 0.0,
            "roi": 0.0,
            "win_rate": 0.0,
        }

    wins = float((picks["result"] == "win").sum())
    losses = float((picks["result"] == "loss").sum())
    pushes = float((picks["result"] == "push").sum())
    staked = float(picks["stake_units"].sum())
    profit = float(picks["profit_units"].sum())
    graded = wins + losses
    return {
        "n_bets": float(len(picks)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "staked_units": staked,
        "profit_units": profit,
        "roi": (profit / staked) if staked > 0 else 0.0,
        "win_rate": (wins / graded) if graded > 0 else 0.0,
    }
