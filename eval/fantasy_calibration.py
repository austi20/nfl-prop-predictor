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


def build_eval_cache(score_year: int = 2025, path: Path | None = None, seed: int = 7) -> Path:
    import warnings

    warnings.simplefilter("ignore")
    import numpy as np

    from api.settings import AppSettings
    from api.services.evaluation_service import scoring_weekly
    from api.services.fantasy_service import (
        _context_factors,
        _predict_distributions,
        _trailing_fantasy_distributions,
    )
    from data.nflverse_loader import load_weekly
    from eval.fantasy_points import SCORING_PROFILES

    settings = AppSettings(
        default_train_years=tuple(range(2015, score_year - 1)), prewarm_fantasy_slate=False
    )
    weekly = scoring_weekly(settings, score_year)
    wk = load_weekly(list(range(2015, score_year + 1)))
    scored = wk[(wk.season == score_year) & (wk.position.isin(["QB", "RB", "WR", "TE"]))].copy()
    scored["career_games"] = scored.groupby("player_id")["week"].transform("size")
    scored = scored[(scored.week >= 2) & (scored.career_games >= _MIN_CAREER_GAMES)]

    rng = np.random.default_rng(seed)
    picks: list[int] = []
    for _pos, grp in scored.groupby("position"):
        idx = grp.index.to_numpy()
        take = rng.choice(idx, size=min(_SAMPLE_PER_POSITION, len(idx)), replace=False)
        picks.extend(int(i) for i in take)

    weights = SCORING_PROFILES["full_ppr"]
    dc = default_calibration()
    rows: list[dict] = []
    for i in picks:
        r = scored.loc[i]
        pid, season, week = str(r.player_id), int(r.season), int(r.week)
        pos = str(r.position).upper()
        team = str(r.get("recent_team", "") or "")
        opp = str(r.get("opponent_team", "") or "")
        try:
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
                recent_team=team, opponent_team=opp, scoring_mode="full_ppr",
                game_id="", calib=dc,
            )
        except Exception:  # noqa: BLE001
            continue
        actual_fp = float(sum((r.get(s, 0.0) or 0.0) * w for s, w in weights.items() if s in r.index))
        rows.append(
            {
                "player_id": pid, "season": season, "week": week, "position": pos,
                "anchor": {s: (d.mean, d.std, d.dist_type) for s, d in anchor_d.items()},
                "glm": {s: (d.mean, d.std, d.dist_type) for s, d in glm.items()},
                "factors": [
                    (f.name, float(f.multiplier), tuple(f.affected_stats)) for f in ctx if f.applied
                ],
                "actual_fp": actual_fp,
            }
        )
    out = path or _EVAL_CACHE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        pickle.dump({"score_year": score_year, "rows": rows}, fh)
    return out


def load_eval_cache(path: Path | None = None) -> dict:
    with open(path or _EVAL_CACHE_PATH, "rb") as fh:
        return pickle.load(fh)
