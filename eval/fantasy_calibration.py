"""Every projection parameter downstream of the trailing-form anchor, in one
tunable object. Defaults reproduce the current board exactly. A tuned instance
is fit by scripts/tune_fantasy_calibration.py against a 2025 backtest and locked
to models/fantasy_calibration.json.

NOT in here (not touched): the anchor mean itself — the recency weights
(linspace(0.5, 1.0, n)), the n/(n+4) shrinkage toward the positional baseline,
the last-8-game window, and the max(recent, base) anchor.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from pathlib import Path

_FACTOR_NAMES = (
    "game_environment", "coaching", "opponent_matchup", "usage_trend", "rest",
    "news", "qb_support", "position_group_form", "weather", "game_script",
)
# The three collinear "this is a good offense" factors that get a joint sub-cap.
OFFENSE_STACK_FACTORS = ("game_environment", "coaching", "qb_support")

_YARDAGE = frozenset({"passing_yards", "rushing_yards", "receiving_yards"})


@dataclass(frozen=True)
class FantasyCalibration:
    glm_blend_weight: float = 0.35
    stat_mean_lo: float = 0.45
    stat_mean_hi: float = 1.70
    yard_cv: float = 0.55
    count_cv: float = 0.85
    cv_floor_frac: float = 0.0  # min game-to-game std as this fraction of (yard/count)_cv * mean; 0 = today
    context_clamp_lo: float = 0.78
    context_clamp_hi: float = 1.22
    offense_stack_cap: float = 1.30  # >= context_clamp_hi -> no-op at the default
    factor_strength: dict[str, float] = field(
        default_factory=lambda: {name: 1.0 for name in _FACTOR_NAMES}
    )
    glm_bias: dict[str, float] = field(default_factory=dict)           # "POS/stat" -> x mean
    glm_var_inflation: dict[str, float] = field(default_factory=dict)  # "POS/stat" -> x std

    def replace(self, **changes) -> "FantasyCalibration":
        return _dc_replace(self, **changes)

    def strength(self, factor: str) -> float:
        return float(self.factor_strength.get(factor, 1.0))

    def to_dict(self) -> dict:
        return {
            "glm_blend_weight": self.glm_blend_weight,
            "stat_mean_lo": self.stat_mean_lo,
            "stat_mean_hi": self.stat_mean_hi,
            "yard_cv": self.yard_cv,
            "count_cv": self.count_cv,
            "cv_floor_frac": self.cv_floor_frac,
            "context_clamp_lo": self.context_clamp_lo,
            "context_clamp_hi": self.context_clamp_hi,
            "offense_stack_cap": self.offense_stack_cap,
            "factor_strength": dict(self.factor_strength),
            "glm_bias": dict(self.glm_bias),
            "glm_var_inflation": dict(self.glm_var_inflation),
        }


def default_calibration() -> FantasyCalibration:
    return FantasyCalibration()


def _from_dict(d: dict) -> FantasyCalibration:
    base = default_calibration()
    fs = {**base.factor_strength, **(d.get("factor_strength") or {})}
    return FantasyCalibration(
        glm_blend_weight=float(d.get("glm_blend_weight", base.glm_blend_weight)),
        stat_mean_lo=float(d.get("stat_mean_lo", base.stat_mean_lo)),
        stat_mean_hi=float(d.get("stat_mean_hi", base.stat_mean_hi)),
        yard_cv=float(d.get("yard_cv", base.yard_cv)),
        count_cv=float(d.get("count_cv", base.count_cv)),
        cv_floor_frac=float(d.get("cv_floor_frac", base.cv_floor_frac)),
        context_clamp_lo=float(d.get("context_clamp_lo", base.context_clamp_lo)),
        context_clamp_hi=float(d.get("context_clamp_hi", base.context_clamp_hi)),
        offense_stack_cap=float(d.get("offense_stack_cap", base.offense_stack_cap)),
        factor_strength={k: float(v) for k, v in fs.items()},
        glm_bias={str(k): float(v) for k, v in (d.get("glm_bias") or {}).items()},
        glm_var_inflation={str(k): float(v) for k, v in (d.get("glm_var_inflation") or {}).items()},
    )


def load_calibration(path: str | Path | None = None) -> FantasyCalibration:
    if path is None:
        return default_calibration()
    p = Path(path)
    if not p.exists():
        return default_calibration()
    try:
        return _from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - a bad artifact must not brick projections
        return default_calibration()


def save_calibration(calib: FantasyCalibration, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(calib.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Backtest evaluation cache
#
# Precompute, once, the raw ingredients for a sample of `score_year` player-weeks:
# the pure trailing-anchor distributions (GLM blend OFF), the raw GLM
# distributions, the actual fantasy points, and every context factor at
# strength 1.0. The sweep then re-applies only the parametric transform, so a
# config eval is milliseconds instead of a model fit.
# ---------------------------------------------------------------------------
import pickle  # noqa: E402

_SAMPLE_PER_POSITION = 700
_MIN_CAREER_GAMES = 3
_EVAL_CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "fantasy_eval_cache_2025.pkl"


def _eval_row_task(task: tuple) -> dict | None:
    """One player-week -> its cached ingredients. Module-level for ProcessPool."""
    import warnings

    warnings.simplefilter("ignore")
    settings, score_year, pid, season, week, pos, team, opp, actual_fp = task
    from api.services.evaluation_service import scoring_weekly
    from api.services.fantasy_service import (
        _context_factors,
        _predict_distributions,
        _trailing_fantasy_distributions,
    )

    dc = default_calibration()
    try:
        weekly = scoring_weekly(settings, score_year)
        glm = _predict_distributions(
            settings, player_id=pid, season=season, week=week,
            opponent_team=opp, position=pos, recent_team=team,
        )
        anchor_d = _trailing_fantasy_distributions(
            weekly, player_id=pid, season=season, week=week, position=pos,
            model_distributions={}, calib=dc,
        )
        ctx = _context_factors(
            settings, weekly, player_id=pid, season=season, week=week, position=pos,
            recent_team=team, opponent_team=opp, scoring_mode="full_ppr", game_id="", calib=dc,
        )
    except Exception:  # noqa: BLE001
        return None
    return {
        "player_id": pid, "season": season, "week": week, "position": pos,
        "anchor": {s: (d.mean, d.std, d.dist_type) for s, d in anchor_d.items()},
        "glm": {s: (d.mean, d.std, d.dist_type) for s, d in glm.items()},
        "factors": [
            (f.name, float(f.multiplier), tuple(f.affected_stats)) for f in ctx if f.applied
        ],
        "actual_fp": actual_fp,
    }


def build_eval_cache(
    score_year: int = 2025, path: Path | None = None, seed: int = 7, workers: int = 0
) -> Path:
    import multiprocessing
    import os
    import warnings
    from concurrent.futures import ProcessPoolExecutor

    warnings.simplefilter("ignore")
    import numpy as np

    from api.settings import AppSettings
    from data.nflverse_loader import load_weekly
    from eval.fantasy_points import SCORING_PROFILES

    settings = AppSettings(
        default_train_years=tuple(range(2015, score_year - 1)), prewarm_fantasy_slate=False
    )
    wk = load_weekly(list(range(2015, score_year + 1)))
    scored = wk[(wk.season == score_year) & (wk.position.isin(["QB", "RB", "WR", "TE"]))].copy()
    scored["career_games"] = scored.groupby("player_id")["week"].transform("size")
    scored = scored[(scored.week >= 2) & (scored.career_games >= _MIN_CAREER_GAMES)]

    rng = np.random.default_rng(seed)
    weights = SCORING_PROFILES["full_ppr"]
    tasks: list[tuple] = []
    for _pos, grp in scored.groupby("position"):
        idx = grp.index.to_numpy()
        take = rng.choice(idx, size=min(_SAMPLE_PER_POSITION, len(idx)), replace=False)
        for i in take:
            r = scored.loc[int(i)]
            actual_fp = float(sum((r.get(s, 0.0) or 0.0) * w for s, w in weights.items() if s in r.index))
            tasks.append((
                settings, score_year, str(r.player_id), int(r.season), int(r.week),
                str(r.position).upper(), str(r.get("recent_team", "") or ""),
                str(r.get("opponent_team", "") or ""), actual_fp,
            ))

    n_workers = workers or max(1, round(0.7 * (os.cpu_count() or 4)))
    rows: list[dict] = []
    if n_workers <= 1 or len(tasks) <= 4:
        rows = [r for r in map(_eval_row_task, tasks) if r is not None]
    else:
        try:
            ctx_mp = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx_mp) as pool:
                rows = [r for r in pool.map(_eval_row_task, tasks, chunksize=4) if r is not None]
        except Exception:  # noqa: BLE001
            rows = [r for r in map(_eval_row_task, tasks) if r is not None]

    out = path or _EVAL_CACHE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        pickle.dump({"score_year": score_year, "rows": rows}, fh)
    return out


def load_eval_cache(path: Path | None = None) -> dict:
    with open(path or _EVAL_CACHE_PATH, "rb") as fh:
        return pickle.load(fh)


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------
_OFFENSE_SET = frozenset(OFFENSE_STACK_FACTORS)
_REALISM_CEIL = {"QB": 34.0, "RB": 28.0, "WR": 30.0, "TE": 22.0}
_BOOM = {"QB": 24.0, "RB": 20.0, "WR": 20.0, "TE": 14.0}
_BUST = {"QB": 14.0, "RB": 8.0, "WR": 7.0, "TE": 5.0}
_POSITIONS = ("QB", "RB", "WR", "TE")
_W_CACHE: dict | None = None


def _fp_weights() -> dict:
    global _W_CACHE
    if _W_CACHE is None:
        from eval.fantasy_points import SCORING_PROFILES

        _W_CACHE = SCORING_PROFILES["full_ppr"]
    return _W_CACHE


def _apply_calib_to_row(row: dict, calib: FantasyCalibration) -> tuple[float, float]:
    """(mean_fp, std_fp) for one player-week under `calib`. Moment-matched sum:
    E[FP] = sum(w * mean), Var[FP] = sum((w * std)^2) (stat independence)."""
    import numpy as np

    weights = _fp_weights()
    pos = row["position"]

    mult: dict[str, float] = {}
    offense: dict[str, float] = {}
    for name, m, stats in row["factors"]:
        scaled = 1.0 + calib.strength(name) * (m - 1.0)
        tgt = offense if name in _OFFENSE_SET else mult
        for st in stats:
            tgt[st] = tgt.get(st, 1.0) * scaled

    mean_fp = 0.0
    var_fp = 0.0
    for st in set(row["anchor"]) | set(row["glm"]):
        w = weights.get(st, 0.0)
        if w == 0.0:
            continue
        a = row["anchor"].get(st)
        g = row["glm"].get(st)
        anchor_mean = a[0] if a else (g[0] if g else 0.0)
        if g and g[0] > 0:
            bias = calib.glm_bias.get(f"{pos}/{st}", 1.0)
            blended = (1.0 - calib.glm_blend_weight) * (a[0] if a else 0.0) \
                + calib.glm_blend_weight * g[0] * bias
        else:
            blended = a[0] if a else 0.0
        anchor_ref = max(anchor_mean, 1e-6)
        blended = float(np.clip(blended, calib.stat_mean_lo * anchor_ref, calib.stat_mean_hi * anchor_ref))
        if blended <= 0:
            continue

        cm = mult.get(st, 1.0) * min(offense.get(st, 1.0), calib.offense_stack_cap)
        cm = float(np.clip(cm, calib.context_clamp_lo, calib.context_clamp_hi))
        final_mean = blended * cm

        is_yard = st in _YARDAGE
        cv = calib.yard_cv if is_yard else calib.count_cv
        if g and g[0] > 0 and g[1] > 0:
            vinf = calib.glm_var_inflation.get(f"{pos}/{st}", 1.0)
            std = g[1] * (final_mean / max(g[0], 1e-6)) * vinf
        else:
            std = cv * final_mean
        std = max(std, cv * calib.cv_floor_frac * final_mean, 1e-6)

        mean_fp += w * final_mean
        var_fp += (w * std) ** 2
    return mean_fp, float(np.sqrt(var_fp)) if var_fp > 0 else 1e-6


def _boom_bust_prob(mean_fp: float, std_fp: float, boom: float, bust: float) -> tuple[float, float]:
    """Lognormal approximation of the (skewed, non-negative) FP sum."""
    import numpy as np
    from scipy import stats as sps

    if mean_fp <= 0 or std_fp <= 0:
        return (1.0 if mean_fp >= boom else 0.0, 1.0 if mean_fp <= bust else 0.0)
    sigma2 = np.log(1.0 + (std_fp / mean_fp) ** 2)
    sigma = np.sqrt(sigma2)
    mu = np.log(mean_fp) - 0.5 * sigma2
    p_boom = float(1.0 - sps.norm.cdf((np.log(boom) - mu) / sigma)) if boom > 0 else 1.0
    p_bust = float(sps.norm.cdf((np.log(max(bust, 1e-6)) - mu) / sigma))
    return p_boom, p_bust


def _calibration_error(probs, hits, bins: int = 10) -> float:
    import numpy as np

    probs = np.asarray(probs, dtype=float)
    hits = np.asarray(hits, dtype=float)
    if len(probs) == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(probs, edges) - 1, 0, bins - 1)
    err = 0.0
    tot = 0
    for b in range(bins):
        m = idx == b
        c = int(m.sum())
        if c == 0:
            continue
        err += c * abs(float(probs[m].mean()) - float(hits[m].mean()))
        tot += c
    return err / max(tot, 1)


def evaluate(calib: FantasyCalibration, cache: dict) -> dict:
    """Per-position-balanced calibration metrics. Every component (MAE, bias,
    boom/bust calibration error, realism penalty, rank correlation) is computed
    per position then averaged over QB/RB/WR/TE with equal weight, so no single
    position dominates the objective."""
    import numpy as np
    from scipy import stats as sps

    rows = cache["rows"]
    n = len(rows)
    proj = np.empty(n)
    act = np.empty(n)
    pboom = np.empty(n)
    hboom = np.empty(n)
    pbust = np.empty(n)
    hbust = np.empty(n)
    over = np.zeros(n)
    pos_arr = np.empty(n, dtype=object)

    for i, r in enumerate(rows):
        m, sd = _apply_calib_to_row(r, calib)
        pos = r["position"]
        proj[i] = m
        act[i] = r["actual_fp"]
        pos_arr[i] = pos
        b, u = _boom_bust_prob(m, sd, _BOOM[pos], _BUST[pos])
        pboom[i] = b
        hboom[i] = 1.0 if r["actual_fp"] >= _BOOM[pos] else 0.0
        pbust[i] = u
        hbust[i] = 1.0 if r["actual_fp"] <= _BUST[pos] else 0.0
        over[i] = max(0.0, m - _REALISM_CEIL[pos])

    per_pos: dict[str, dict] = {}
    for pos in _POSITIONS:
        mask = pos_arr == pos
        if mask.sum() < 10:
            continue
        p = proj[mask]
        a = act[mask]
        rc = float(sps.spearmanr(p, a).statistic) if mask.sum() > 20 else 0.0
        per_pos[pos] = {
            "n": int(mask.sum()),
            "mae": float(np.mean(np.abs(p - a))),
            "bias": float(np.mean(p - a)),
            "boom_calib_err": _calibration_error(pboom[mask], hboom[mask]),
            "bust_calib_err": _calibration_error(pbust[mask], hbust[mask]),
            "realism_penalty": float(np.mean(over[mask])),
            "rank_corr": rc,
            "max_proj": float(np.max(p)),
            "pred_boom_rate": float(np.mean(pboom[mask])),
            "actual_boom_rate": float(np.mean(hboom[mask])),
        }

    def avg(key: str) -> float:
        vals = [v[key] for v in per_pos.values()]
        return float(np.mean(vals)) if vals else 0.0

    mae = avg("mae")
    bias_abs = float(np.mean([abs(v["bias"]) for v in per_pos.values()])) if per_pos else 0.0
    boom_err = avg("boom_calib_err")
    bust_err = avg("bust_calib_err")
    realism = avg("realism_penalty")
    rank_corr = avg("rank_corr")
    objective = (
        1.0 * mae + 1.5 * bias_abs + 8.0 * boom_err + 8.0 * bust_err
        + 2.0 * realism - 6.0 * rank_corr
    )
    return {
        "objective": objective,
        "mae": mae,
        "bias_abs": bias_abs,
        "boom_calib_err": boom_err,
        "bust_calib_err": bust_err,
        "realism_penalty": realism,
        "rank_corr": rank_corr,
        "n": n,
        "per_position": per_pos,
    }


# ---------------------------------------------------------------------------
# Analytic GLM bias / variance correction (fit on completed pre-score seasons)
# ---------------------------------------------------------------------------
def fit_glm_correction(
    fit_years: tuple[int, ...] = (2023, 2024),
    n_per_pos: int = 500,
    seed: int = 11,
) -> tuple[dict[str, float], dict[str, float]]:
    """For every (position, stat) the position GLM covers — QB passing_yards/tds/
    interceptions, RB rushing_yards/tds, WR & TE receptions/receiving_yards/
    receiving_tds — compare the GLM prediction to the actual on `fit_years`:

      glm_bias[p/s]          = median(actual) / median(pred_mean)   (robust to the elite tail)
      glm_var_inflation[p/s] = std(actual - pred_mean) / mean(pred_std)   clipped [0.8, 2.5]
    """
    import warnings

    warnings.simplefilter("ignore")
    import numpy as np

    from api.settings import AppSettings
    from api.services.evaluation_service import scoring_weekly
    from api.services.fantasy_service import _MODEL_STATS_BY_POSITION, _predict_distributions
    from data.nflverse_loader import load_weekly

    settings = AppSettings(
        default_train_years=tuple(range(2015, min(fit_years))), prewarm_fantasy_slate=False
    )
    _ = scoring_weekly(settings, max(fit_years))  # warm caches / widen the fit window
    wk = load_weekly(list(range(2015, max(fit_years) + 1)))
    pool = wk[
        wk.season.isin(fit_years)
        & wk.position.isin(["QB", "RB", "WR", "TE"])
        & (wk.week >= 3)
    ]
    rng = np.random.default_rng(seed)

    acc: dict[str, list[tuple[float, float, float]]] = {}
    for pos, grp in pool.groupby("position"):
        pos_u = str(pos).upper()
        idx = rng.choice(grp.index.to_numpy(), size=min(n_per_pos, len(grp)), replace=False)
        for i in idx:
            r = grp.loc[i]
            try:
                d = _predict_distributions(
                    settings, player_id=str(r.player_id), season=int(r.season), week=int(r.week),
                    opponent_team=str(r.get("opponent_team", "") or ""), position=pos_u,
                    recent_team=str(r.get("recent_team", "") or ""),
                )
            except Exception:  # noqa: BLE001
                continue
            for st in _MODEL_STATS_BY_POSITION.get(pos_u, ()):
                dd = d.get(st)
                if dd is None or dd.mean <= 0:
                    continue
                acc.setdefault(f"{pos_u}/{st}", []).append(
                    (float(dd.mean), float(dd.std), float(r.get(st, 0.0) or 0.0))
                )

    bias: dict[str, float] = {}
    vinf: dict[str, float] = {}
    for key, vals in acc.items():
        if len(vals) < 40:
            continue
        pm = np.array([v[0] for v in vals])
        ps = np.array([v[1] for v in vals])
        a = np.array([v[2] for v in vals])
        bias[key] = float(np.clip(np.median(a) / max(np.median(pm), 1e-6), 0.6, 1.4))
        resid_sd = float(np.std(a - pm))
        vinf[key] = float(np.clip(resid_sd / max(np.mean(ps), 1e-6), 0.8, 2.5))
    return bias, vinf
