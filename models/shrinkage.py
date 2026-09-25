"""Per-stat shrinkage weights for the position GLMs.

Each model blends its GLM prediction back toward the league prior:

    shrunk = prior_mean + w * (glm_prediction - prior_mean)

`w` used to be `n / (n + k)` with `n` counting *same-season* games played. That
made the weight ramp from 0.33 in week 2 to 0.85 by week 11, so every
early-season projection collapsed onto the league mean: high-usage players came
out ~20-26% low, which put a spurious "under" edge on every prop Kalshi lists.

Measuring the weight that actually minimises squared error shows it is close to
flat in `n` -- the GLM's rolling features already span season boundaries, so its
evidence base barely depends on how many games the current season has had. What
does vary is the stat: a target share is far more predictable than a rushing
touchdown. So the weight is per stat and constant in `n`, fitted by least
squares on walk-forward rows (see scripts/diag/fit_shrinkage_weights.py).

A stat whose weight moves around across seasons is not trusted; it falls back to
the median weight instead.
"""
from __future__ import annotations

import json
from functools import lru_cache

from data.nflverse_loader import bundle_root

# Frozen sidecar reads the copy Tauri ships next to the exe.
_WEIGHTS_FILE = bundle_root() / "models" / "shrinkage_weights.json"

# Above this leave-one-season-out coefficient of variation the fitted weight is
# noise rather than a property of the stat, so the default is used instead.
_MAX_LOO_CV = 0.25

# Used when the weights file is missing entirely. Close to the fitted median, so
# a lost config degrades to "trust the GLM most of the way" rather than to the
# old early-season collapse.
_FALLBACK = 0.81


@lru_cache(maxsize=1)
def _load() -> tuple[float, dict[str, float]]:
    try:
        raw = json.loads(_WEIGHTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _FALLBACK, {}
    default = float(raw.get("default", _FALLBACK))
    cv = raw.get("loo_cv", {}) or {}
    weights = {
        key: float(value)
        for key, value in (raw.get("weights", {}) or {}).items()
        if float(cv.get(key, 0.0)) <= _MAX_LOO_CV
    }
    return default, weights


def shrinkage_weight(model_name: str, stat: str) -> float:
    """Weight on the GLM's deviation from the league prior for this stat."""
    default, weights = _load()
    return weights.get(f"{model_name}/{stat}", default)
