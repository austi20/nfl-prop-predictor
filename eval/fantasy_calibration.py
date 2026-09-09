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
