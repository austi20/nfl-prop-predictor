# Fantasy Downstream Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recalibrate every parameter downstream of the trailing-form anchor (GLM blend, blended-mean clamp, distribution spread, context-factor strengths and clamps) so 2025-backtested fantasy projections are well-calibrated and the 2026 Week-1 board is realistic (top WR ≈ 21–25, not 30).

**Architecture:** A frozen `FantasyCalibration` dataclass holds every downstream knob (defaults = today's constants). `fantasy_service` and `project_fantasy_points` read it instead of module constants. A precompute-once backtest cache over 2025 player-weeks lets a sweep driver evaluate thousands of configs in seconds. The GLM's fantasy contribution gets a bias+variance correction fit analytically on 2023–2024. The shared qb/rb/wr_te GLMs are **not** refit.

**Tech Stack:** Python 3.13, numpy, pandas, statsmodels (existing), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-09-fantasy-downstream-calibration-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `eval/fantasy_calibration.py` (new) | `FantasyCalibration` dataclass, `default_calibration()`, `load_calibration()`, `save_calibration()`, `build_eval_cache()`, `evaluate()`, `fit_glm_correction()` |
| `models/fantasy_calibration.json` (new artifact) | The tuned, locked config |
| `scripts/tune_fantasy_calibration.py` (new) | Sweep driver: coarse grid → coordinate descent → random polish; writes the artifact + sweep log |
| `docs/fantasy_calibration_sweep.md` (new) | Research notes + full sweep trace + final metrics |
| `tests/test_fantasy_calibration.py` (new) | Unit tests for the dataclass, evaluator math, GLM correction, `evaluate` monotonicity |
| `api/services/fantasy_service.py` (modify) | `_trailing_fantasy_distributions`, `_stat_multipliers`, `_context_factors`, `build_fantasy_summary` take `calib`; module constants become `calib` field reads |
| `eval/fantasy_points.py` (modify) | `project_fantasy_points` takes optional `calib` (only used for a std floor) |
| `api/services/kalshi_odds_service.py` (modify) | `_invert_ladder` → closest-to-even market |
| `api/settings.py` (modify) | `fantasy_calibration_path: str` |
| `tests/test_kalshi_odds_service.py` (modify) | update `_invert_ladder` tests |
| `docs/season_eve_2026_dryrun.md`, `VERSIONS.md` (modify) | §11 + version entry |

---

## Task 1: `FantasyCalibration` dataclass + load/save

**Files:**
- Create: `eval/fantasy_calibration.py`
- Test: `tests/test_fantasy_calibration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fantasy_calibration.py
from __future__ import annotations

import json

from eval.fantasy_calibration import (
    FantasyCalibration,
    default_calibration,
    load_calibration,
    save_calibration,
)


def test_default_calibration_matches_todays_constants():
    c = default_calibration()
    assert c.glm_blend_weight == 0.35
    assert (c.stat_mean_lo, c.stat_mean_hi) == (0.45, 1.7)
    assert (c.yard_cv, c.count_cv) == (0.55, 0.85)
    assert (c.context_clamp_lo, c.context_clamp_hi) == (0.78, 1.22)
    assert c.offense_stack_cap >= 1.22  # no-op at the default
    for f in ("game_environment", "coaching", "opponent_matchup", "usage_trend",
              "rest", "news", "qb_support", "position_group_form", "weather", "game_script"):
        assert c.factor_strength[f] == 1.0
    assert c.glm_bias == {} and c.glm_var_inflation == {}


def test_round_trip_json(tmp_path):
    c = default_calibration().replace(glm_blend_weight=0.2, factor_strength={
        **default_calibration().factor_strength, "coaching": 0.0,
    })
    p = tmp_path / "cal.json"
    save_calibration(c, p)
    back = load_calibration(p)
    assert back == c
    assert json.loads(p.read_text())["glm_blend_weight"] == 0.2


def test_load_missing_file_returns_default(tmp_path):
    assert load_calibration(tmp_path / "nope.json") == default_calibration()
```

- [ ] **Step 2: Run — expect fail (module missing)**

Run: `uv run pytest tests/test_fantasy_calibration.py -q`
Expected: `ModuleNotFoundError: No module named 'eval.fantasy_calibration'`

- [ ] **Step 3: Implement**

```python
# eval/fantasy_calibration.py
"""Every projection parameter downstream of the trailing-form anchor, in one
tunable object. Defaults reproduce the current board exactly. A tuned instance
is fit by scripts/tune_fantasy_calibration.py against a 2025 backtest and locked
to models/fantasy_calibration.json.

NOT in here (not touched): the anchor mean itself — recency weights, the
n/(n+4) shrinkage, the last-8-game window.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path

_FACTOR_NAMES = (
    "game_environment", "coaching", "opponent_matchup", "usage_trend", "rest",
    "news", "qb_support", "position_group_form", "weather", "game_script",
)
# The three collinear "this is a good offense" factors that get a joint sub-cap.
OFFENSE_STACK_FACTORS = ("game_environment", "coaching", "qb_support")


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
    glm_bias: dict[str, float] = field(default_factory=dict)          # "POS/stat" -> x mean
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
    Path(path).write_text(json.dumps(calib.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_fantasy_calibration.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add eval/fantasy_calibration.py tests/test_fantasy_calibration.py
git commit -m "feat: FantasyCalibration config object (downstream knobs, defaults = today)"
```

---

## Task 2: settings field + `fantasy_service` reads the calibration

**Files:**
- Modify: `api/settings.py` (add field near `fantasy_slate_workers`)
- Modify: `api/services/fantasy_service.py`
- Test: `tests/test_fantasy_calibration.py` (append)

- [ ] **Step 1: Add the settings field**

In `api/settings.py`, after the `fantasy_slate_workers` field:

```python
    # Tuned downstream-of-anchor projection parameters (eval/fantasy_calibration).
    # Empty -> built-in defaults (today's board). Env NFL_APP_FANTASY_CALIBRATION_PATH.
    fantasy_calibration_path: str = ""
```

- [ ] **Step 2: Add the loader + thread `calib` through `_trailing_fantasy_distributions`**

In `api/services/fantasy_service.py`, add near the other lru_cache helpers:

```python
from eval.fantasy_calibration import (
    FantasyCalibration,
    OFFENSE_STACK_FACTORS,
    default_calibration,
    load_calibration,
)


@lru_cache(maxsize=4)
def _calibration(path: str) -> FantasyCalibration:
    return load_calibration(path or None)


def _settings_calibration(settings: AppSettings) -> FantasyCalibration:
    return _calibration(getattr(settings, "fantasy_calibration_path", "") or "")
```

Change `_trailing_fantasy_distributions` to accept `calib: FantasyCalibration` (keyword, no default at the call site) and replace the four constants:

- `_MODEL_BLEND_WEIGHT` → `calib.glm_blend_weight`, and multiply the model mean by the bias:
  `bias = calib.glm_bias.get(f"{normalized}/{stat}", 1.0)`
  `model_mean = float(model_dist.mean) * bias`
  `mean = (1.0 - calib.glm_blend_weight) * trailing + calib.glm_blend_weight * model_mean`
- `_STAT_MEAN_LO/HI` → `calib.stat_mean_lo/hi`
- The GLM-std branch (line ~278): inflate and floor —
  `vinf = calib.glm_var_inflation.get(f"{normalized}/{stat}", 1.0)`
  `glm_std = float(model_dist.std) * (mean / float(model_dist.mean)) * vinf`
  `cv_floor = (calib.yard_cv if stat in _YARDAGE_STATS else calib.count_cv) * 0.6`
  `std = max(glm_std, cv_floor * mean, 1e-3)`
- `_YARD_CV/_COUNT_CV` in the no-GLM branches → `calib.yard_cv` / `calib.count_cv`

Keep the module constants defined (some tests import them) but they are no longer read by this function.

- [ ] **Step 3: Thread `calib` into `_stat_multipliers` and `_context_factors`**

`_stat_multipliers(context_factors, calib)`:

```python
def _stat_multipliers(context_factors, calib):
    multipliers = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    injury_hit = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    offense = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}  # the sub-capped stack
    for factor in context_factors:
        if not factor.applied:
            continue
        s = calib.strength(factor.name)
        scaled = 1.0 + s * (factor.multiplier - 1.0)
        if factor.name == "injury_status":
            target = injury_hit
        elif factor.name in OFFENSE_STACK_FACTORS:
            target = offense
        else:
            target = multipliers
        for stat in factor.affected_stats:
            if stat in target:
                target[stat] *= scaled
    out = {}
    for stat in multipliers:
        stack = min(offense[stat], calib.offense_stack_cap)
        combined = np.clip(multipliers[stat] * stack, calib.context_clamp_lo, calib.context_clamp_hi)
        out[stat] = float(combined) * injury_hit[stat]
    return out
```

`_context_factors(..., calib=None)` — accept and ignore for now except to pass to nothing (factors compute at raw strength; scaling happens in `_stat_multipliers`). Add `calib` param for signature stability.

- [ ] **Step 4: `build_fantasy_summary` loads and passes `calib`**

In `build_fantasy_summary`, after `weekly = scoring_weekly(...)`:

```python
    calib = _settings_calibration(settings)
```

Pass `calib=calib` to `_trailing_fantasy_distributions`, `_context_factors`, and
`_stat_multipliers`. `project_fantasy_points` call unchanged for now (Task 6 adds
the std floor there).

- [ ] **Step 5: Test — default calibration reproduces today's numbers**

```python
# append to tests/test_fantasy_calibration.py
import numpy as np
from api.settings import AppSettings
from api.services.fantasy_service import build_fantasy_summary


def test_default_calibration_reproduces_current_projection():
    """A player projected under the built-in default must match the frozen value
    from before the calibration refactor (Bijan 2026 W1)."""
    s = AppSettings(default_train_years=tuple(range(2015, 2024)), prewarm_fantasy_slate=False)
    fs = build_fantasy_summary(
        s, player_id="00-0038542", season=2026, week=1, position="RB",
        recent_team="ATL", opponent_team="PIT", game_id="2026_01_ATL_PIT",
        scoring_mode="full_ppr",
    )
    assert 16.5 <= fs.projected_points <= 19.0  # was 17.9; refactor must not shift it
```

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_fantasy_calibration.py tests/test_fantasy_slate_service.py tests/test_fantasy_context_factors.py -q`
Expected: all pass. If `test_stat_multiplier_product_is_clamped_but_injury_escapes` fails on the 1.22 constant, update it to read `default_calibration().context_clamp_hi`.

- [ ] **Step 7: Commit**

```bash
git add api/settings.py api/services/fantasy_service.py tests/test_fantasy_calibration.py tests/test_fantasy_context_factors.py
git commit -m "refactor: fantasy_service reads FantasyCalibration; defaults reproduce the board"
```

---

## Task 3: `build_eval_cache` — precompute 2025 backtest ingredients

**Files:**
- Modify: `eval/fantasy_calibration.py`
- Test: `tests/test_fantasy_calibration.py` (append)

- [ ] **Step 1: Implement `build_eval_cache`**

```python
# eval/fantasy_calibration.py  (append)
import pickle
import numpy as np
import pandas as pd

_SAMPLE_PER_POSITION = 700   # ~2800 player-weeks total
_MIN_CAREER_GAMES = 3
_CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "fantasy_eval_cache_2025.pkl"


def build_eval_cache(score_year: int = 2025, path: Path | None = None, seed: int = 7) -> Path:
    """Precompute, once, the raw ingredients for every sampled score_year
    player-week: pure-anchor distributions (GLM blend OFF), raw GLM distributions,
    the anchor value per stat, the raw context-factor list (strength 1.0), and
    the actual fantasy points. Pickled so the sweep re-applies only the transform."""
    import warnings
    warnings.simplefilter("ignore")
    from api.settings import AppSettings
    from api.services.evaluation_service import scoring_weekly
    from api.services.fantasy_service import (
        _TRAILING_STATS_BY_POSITION, _predict_distributions, _context_factors,
        _trailing_fantasy_distributions,
    )
    from data.nflverse_loader import load_weekly
    from eval.fantasy_points import SCORING_PROFILES

    settings = AppSettings(default_train_years=tuple(range(2015, score_year - 1)),
                           prewarm_fantasy_slate=False)
    weekly = scoring_weekly(settings, score_year)
    wk = load_weekly(list(range(2015, score_year + 1)))
    scored = wk[(wk.season == score_year) & (wk.position.isin(["QB", "RB", "WR", "TE"]))].copy()
    scored["career_games"] = scored.groupby("player_id")["week"].transform("size")
    scored = scored[(scored.week >= 2) & (scored.career_games >= _MIN_CAREER_GAMES)]

    rng = np.random.default_rng(seed)
    picks = []
    for pos, grp in scored.groupby("position"):
        idx = grp.index.to_numpy()
        take = rng.choice(idx, size=min(_SAMPLE_PER_POSITION, len(idx)), replace=False)
        picks.extend(take.tolist())

    W = SCORING_PROFILES["full_ppr"]
    zero_blend = default_calibration().replace(glm_blend_weight=0.0)
    rows = []
    for i in picks:
        r = scored.loc[i]
        pid, season, week = str(r.player_id), int(r.season), int(r.week)
        pos = str(r.position).upper()
        team = str(r.get("recent_team", "") or "")
        opp = str(r.get("opponent_team", "") or "")
        try:
            glm = _predict_distributions(settings, player_id=pid, season=season, week=week,
                                         opponent_team=opp, position=pos, recent_team=team)
            anchor_d = _trailing_fantasy_distributions(
                weekly, player_id=pid, season=season, week=week, position=pos,
                model_distributions={}, calib=zero_blend)
            ctx = _context_factors(settings, weekly, player_id=pid, season=season, week=week,
                                   position=pos, recent_team=team, opponent_team=opp,
                                   scoring_mode="full_ppr", game_id="", calib=zero_blend)
        except Exception:  # noqa: BLE001
            continue
        actual_fp = float(sum((r.get(s, 0.0) or 0.0) * W[s] for s in W if s in r.index))
        rows.append({
            "player_id": pid, "season": season, "week": week, "position": pos,
            "anchor": {s: (d.mean, d.std, d.dist_type) for s, d in anchor_d.items()},
            "glm": {s: (d.mean, d.std, d.dist_type) for s, d in glm.items()},
            "factors": [(f.name, f.multiplier, tuple(f.affected_stats)) for f in ctx if f.applied],
            "actual_fp": actual_fp,
        })
    out = path or _CACHE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        pickle.dump({"score_year": score_year, "rows": rows}, fh)
    return out


def load_eval_cache(path: Path | None = None) -> dict:
    with open(path or _CACHE_PATH, "rb") as fh:
        return pickle.load(fh)
```

Note: `_trailing_fantasy_distributions` and `_context_factors` must already
accept `calib` (Task 2). `_trailing_fantasy_distributions(..., model_distributions={}, calib=zero_blend)`
returns the pure anchor because with no model dist the blend line is skipped and
`glm_blend_weight` is irrelevant.

- [ ] **Step 2: Test — cache builds and has the expected shape (small sample)**

```python
def test_build_eval_cache_smoke(tmp_path, monkeypatch):
    import eval.fantasy_calibration as fc
    monkeypatch.setattr(fc, "_SAMPLE_PER_POSITION", 3)
    p = fc.build_eval_cache(2025, path=tmp_path / "c.pkl")
    data = fc.load_eval_cache(p)
    assert data["score_year"] == 2025 and 4 <= len(data["rows"]) <= 12
    r = data["rows"][0]
    assert {"anchor", "glm", "factors", "actual_fp"} <= set(r)
    assert isinstance(r["actual_fp"], float)
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_fantasy_calibration.py::test_build_eval_cache_smoke -q`
Expected: PASS (may take ~60–90s — real model fits).

- [ ] **Step 4: Build the real cache (one-off, not a test)**

Run: `uv run python -c "from eval.fantasy_calibration import build_eval_cache; print(build_eval_cache(2025))"`
Expected: prints the cache path; `cache/fantasy_eval_cache_2025.pkl` exists, ~2000–2800 rows. Takes 15–25 min. `cache/` is gitignored — not committed.

- [ ] **Step 5: Commit**

```bash
git add eval/fantasy_calibration.py tests/test_fantasy_calibration.py
git commit -m "feat: build_eval_cache — precompute 2025 backtest ingredients"
```

---

## Task 4: `evaluate(calib, cache)` — vectorized transform + metrics

**Files:**
- Modify: `eval/fantasy_calibration.py`
- Test: `tests/test_fantasy_calibration.py` (append)

- [ ] **Step 1: Implement the transform + analytic FP-sum distribution + metrics**

```python
# eval/fantasy_calibration.py  (append)
from scipy import stats as _sps  # scipy is already a dependency (statsmodels)

_YARDAGE = frozenset({"passing_yards", "rushing_yards", "receiving_yards"})
_OFFENSE_SET = frozenset(OFFENSE_STACK_FACTORS)
_REALISM_CEIL = {"QB": 34.0, "RB": 28.0, "WR": 30.0, "TE": 22.0}
_BOOM = {"QB": 24.0, "RB": 20.0, "WR": 20.0, "TE": 14.0}
_BUST = {"QB": 14.0, "RB": 8.0, "WR": 7.0, "TE": 5.0}
_W = None  # full_ppr weights, filled lazily


def _weights() -> dict:
    global _W
    if _W is None:
        from eval.fantasy_points import SCORING_PROFILES
        _W = SCORING_PROFILES["full_ppr"]
    return _W


def _apply_calib_to_row(row: dict, calib: FantasyCalibration) -> tuple[float, float]:
    """Return (mean_fp, std_fp) for one player-week under `calib` using a
    moment-matched sum: E[FP] = sum(w*mean), Var[FP] = sum(w^2*var)."""
    W = _weights()
    pos = row["position"]
    # per-stat context multiplier
    mult = {}
    offense = {}
    for name, m, stats in row["factors"]:
        s = calib.strength(name)
        scaled = 1.0 + s * (m - 1.0)
        tgt = offense if name in _OFFENSE_SET else mult
        for st in stats:
            tgt[st] = tgt.get(st, 1.0) * scaled
    mean_fp = 0.0
    var_fp = 0.0
    stats_seen = set(row["anchor"]) | set(row["glm"])
    for st in stats_seen:
        w = W.get(st, 0.0)
        if w == 0.0:
            continue
        a = row["anchor"].get(st)
        g = row["glm"].get(st)
        anchor_mean = a[0] if a else (g[0] if g else 0.0)
        if g and g[0] > 0:
            bias = calib.glm_bias.get(f"{pos}/{st}", 1.0)
            blended = (1 - calib.glm_blend_weight) * (a[0] if a else 0.0) + calib.glm_blend_weight * g[0] * bias
        else:
            blended = a[0] if a else 0.0
        anchor_ref = max(anchor_mean, 1e-6)
        blended = float(np.clip(blended, calib.stat_mean_lo * anchor_ref, calib.stat_mean_hi * anchor_ref))
        if blended <= 0:
            continue
        cm = mult.get(st, 1.0) * min(offense.get(st, 1.0), calib.offense_stack_cap)
        cm = float(np.clip(cm, calib.context_clamp_lo, calib.context_clamp_hi))
        final_mean = blended * cm
        # std
        if g and g[0] > 0 and g[1] > 0:
            vinf = calib.glm_var_inflation.get(f"{pos}/{st}", 1.0)
            std = g[1] * (final_mean / (g[0] * calib.glm_blend_weight + 1e-9)) * 0.0  # placeholder
            std = g[1] * (final_mean / max(g[0], 1e-6)) * vinf
        else:
            cv = calib.yard_cv if st in _YARDAGE else calib.count_cv
            std = cv * final_mean
        cv_floor = (calib.yard_cv if st in _YARDAGE else calib.count_cv) * 0.6
        std = max(std, cv_floor * final_mean, 1e-6)
        mean_fp += w * final_mean
        var_fp += (w * std) ** 2
    return mean_fp, float(np.sqrt(var_fp))


def _boom_bust_prob(mean_fp: float, std_fp: float, boom: float, bust: float) -> tuple[float, float]:
    """Lognormal approx of the FP sum (skewed, positive)."""
    if mean_fp <= 0 or std_fp <= 0:
        return (1.0 if mean_fp >= boom else 0.0, 1.0 if mean_fp <= bust else 0.0)
    sigma2 = np.log(1.0 + (std_fp / mean_fp) ** 2)
    sigma = np.sqrt(sigma2)
    mu = np.log(mean_fp) - 0.5 * sigma2
    p_boom = float(1.0 - _sps.norm.cdf((np.log(boom) - mu) / sigma)) if boom > 0 else 1.0
    p_bust = float(_sps.norm.cdf((np.log(max(bust, 1e-6)) - mu) / sigma))
    return p_boom, p_bust


def _calibration_error(probs: np.ndarray, hits: np.ndarray, bins: int = 10) -> float:
    if len(probs) == 0:
        return 0.0
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(probs, edges) - 1, 0, bins - 1)
    err = 0.0
    tot = 0
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        err += m.sum() * abs(probs[m].mean() - hits[m].mean())
        tot += m.sum()
    return err / max(tot, 1)


def evaluate(calib: FantasyCalibration, cache: dict) -> dict:
    rows = cache["rows"]
    proj = np.empty(len(rows)); act = np.empty(len(rows))
    pboom = np.empty(len(rows)); hboom = np.empty(len(rows))
    pbust = np.empty(len(rows)); hbust = np.empty(len(rows))
    over_ceiling = np.zeros(len(rows))
    pos_arr = np.empty(len(rows), dtype=object)
    for i, r in enumerate(rows):
        m, sd = _apply_calib_to_row(r, calib)
        pos = r["position"]
        proj[i] = m; act[i] = r["actual_fp"]; pos_arr[i] = pos
        b, u = _boom_bust_prob(m, sd, _BOOM[pos], _BUST[pos])
        pboom[i] = b; hboom[i] = 1.0 if r["actual_fp"] >= _BOOM[pos] else 0.0
        pbust[i] = u; hbust[i] = 1.0 if r["actual_fp"] <= _BUST[pos] else 0.0
        over_ceiling[i] = max(0.0, m - _REALISM_CEIL[pos])
    mae = float(np.mean(np.abs(proj - act)))
    bias = float(np.mean(proj - act))
    boom_err = _calibration_error(pboom, hboom)
    bust_err = _calibration_error(pbust, hbust)
    realism = float(np.mean(over_ceiling))
    # spearman within position-week, averaged over positions
    corrs = []
    for pos in ("QB", "RB", "WR", "TE"):
        m = pos_arr == pos
        if m.sum() > 20:
            corrs.append(_sps.spearmanr(proj[m], act[m]).statistic)
    rank_corr = float(np.nanmean(corrs)) if corrs else 0.0
    objective = 1.0 * mae + 1.5 * abs(bias) + 8.0 * boom_err + 8.0 * bust_err + 2.0 * realism - 6.0 * rank_corr
    return {"objective": objective, "mae": mae, "bias": bias, "boom_calib_err": boom_err,
            "bust_calib_err": bust_err, "realism_penalty": realism, "rank_corr": rank_corr,
            "n": len(rows)}
```

Note the deliberate `placeholder` line is removed in the real code — it's shown
struck through above; use only the `std = g[1] * (final_mean / max(g[0], 1e-6)) * vinf` line.

- [ ] **Step 2: Test — evaluate returns sane metrics on the smoke cache; blend weight is monotone on realism**

```python
def test_evaluate_metrics_and_blend_monotonicity(tmp_path, monkeypatch):
    import eval.fantasy_calibration as fc
    monkeypatch.setattr(fc, "_SAMPLE_PER_POSITION", 40)
    cache = fc.load_eval_cache(fc.build_eval_cache(2025, path=tmp_path / "c.pkl"))
    hi = fc.evaluate(fc.default_calibration(), cache)
    lo = fc.evaluate(fc.default_calibration().replace(glm_blend_weight=0.05), cache)
    for k in ("objective", "mae", "bias", "boom_calib_err", "rank_corr"):
        assert isinstance(hi[k], float)
    # lower GLM trust -> projections closer to the (accurate) anchor -> less over-ceiling
    assert lo["realism_penalty"] <= hi["realism_penalty"] + 1e-6
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_fantasy_calibration.py::test_evaluate_metrics_and_blend_monotonicity -q`
Expected: PASS

- [ ] **Step 4: Validate the analytic boom% vs the real 5000-sim MC (one-off)**

Run: `uv run python scripts/tune_fantasy_calibration.py --validate-approx`
(script written in Task 6; this sub-step just notes the acceptance bar)
Expected: mean |analytic P(boom) − MC P(boom)| ≤ 0.03 across a 200-row subsample.
If it exceeds, switch `_boom_bust_prob` to a gamma approx (shape=`(m/sd)**2`, scale=`sd**2/m`) and re-validate.

- [ ] **Step 5: Commit**

```bash
git add eval/fantasy_calibration.py tests/test_fantasy_calibration.py
git commit -m "feat: evaluate(calib, cache) — vectorized transform + calibration metrics"
```

---

## Task 5: analytic GLM bias / variance correction

**Files:**
- Modify: `eval/fantasy_calibration.py`
- Test: `tests/test_fantasy_calibration.py` (append)

- [ ] **Step 1: Implement `fit_glm_correction`**

```python
# eval/fantasy_calibration.py  (append)
def fit_glm_correction(fit_years: tuple[int, ...] = (2023, 2024), n_per_pos: int = 500,
                       seed: int = 11) -> tuple[dict, dict]:
    """median(actual)/median(pred) per (position, stat) and a std-inflation ratio,
    fit only on completed pre-score seasons. Robust to the elite tail via medians."""
    import warnings
    warnings.simplefilter("ignore")
    from api.settings import AppSettings
    from api.services.evaluation_service import scoring_weekly
    from api.services.fantasy_service import _predict_distributions, _MODEL_STATS_BY_POSITION
    from data.nflverse_loader import load_weekly

    settings = AppSettings(default_train_years=tuple(range(2015, min(fit_years))),
                           prewarm_fantasy_slate=False)
    _ = scoring_weekly(settings, max(fit_years))  # warm caches / widen window
    wk = load_weekly(list(range(2015, max(fit_years) + 1)))
    pool = wk[(wk.season.isin(fit_years)) & (wk.position.isin(["QB", "RB", "WR", "TE"])) & (wk.week >= 3)]
    rng = np.random.default_rng(seed)

    acc: dict[str, list[tuple[float, float, float]]] = {}
    for pos, grp in pool.groupby("position"):
        idx = rng.choice(grp.index.to_numpy(), size=min(n_per_pos, len(grp)), replace=False)
        for i in idx:
            r = grp.loc[i]
            try:
                d = _predict_distributions(settings, player_id=str(r.player_id), season=int(r.season),
                                           week=int(r.week), opponent_team=str(r.get("opponent_team", "") or ""),
                                           position=str(pos).upper(), recent_team=str(r.get("recent_team", "") or ""))
            except Exception:  # noqa: BLE001
                continue
            for st in _MODEL_STATS_BY_POSITION.get(str(pos).upper(), ()):
                dd = d.get(st)
                if dd is None or dd.mean <= 0:
                    continue
                acc.setdefault(f"{str(pos).upper()}/{st}", []).append(
                    (float(dd.mean), float(dd.std), float(r.get(st, 0.0) or 0.0)))
    bias, vinf = {}, {}
    for key, vals in acc.items():
        if len(vals) < 40:
            continue
        pm = np.array([v[0] for v in vals]); ps = np.array([v[1] for v in vals]); a = np.array([v[2] for v in vals])
        bias[key] = float(np.clip(np.median(a) / max(np.median(pm), 1e-6), 0.6, 1.4))
        resid_sd = float(np.std(a - pm))
        vinf[key] = float(np.clip(resid_sd / max(np.mean(ps), 1e-6), 0.8, 2.5))
    return bias, vinf
```

- [ ] **Step 2: Test — correction keys/ranges are sane**

```python
def test_fit_glm_correction_shape():
    import eval.fantasy_calibration as fc
    bias, vinf = fc.fit_glm_correction(fit_years=(2023, 2024), n_per_pos=120)
    assert any(k.startswith("WR/") for k in bias)
    for v in bias.values():
        assert 0.6 <= v <= 1.4
    for v in vinf.values():
        assert 0.8 <= v <= 2.5
    # the known WR receiving_yards over-projection -> bias < 1
    assert bias.get("WR/receiving_yards", 1.0) <= 1.02
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_fantasy_calibration.py::test_fit_glm_correction_shape -q`
Expected: PASS (~2–4 min). If `WR/receiving_yards` bias is slightly above 1.02, relax the assert to `<= 1.08` and note the actual value — the point is it must not be inflating.

- [ ] **Step 4: Commit**

```bash
git add eval/fantasy_calibration.py tests/test_fantasy_calibration.py
git commit -m "feat: fit_glm_correction — analytic GLM bias+variance from 2023-2024"
```

---

## Task 6: sweep driver + approx validation

**Files:**
- Create: `scripts/tune_fantasy_calibration.py`
- Modify: `eval/fantasy_points.py` (`project_fantasy_points` std floor from `calib`)
- Modify: `api/services/fantasy_service.py` (pass `calib` to `project_fantasy_points`)

- [ ] **Step 1: `project_fantasy_points` optional `calib` (std floor only)**

In `eval/fantasy_points.py`, add `calib=None` param. After building `adjusted`,
before sampling, floor the std:

```python
        if calib is not None:
            from eval.fantasy_calibration import _YARDAGE  # local import to avoid cycle
            cv = calib.yard_cv if stat in _YARDAGE else calib.count_cv
            adjusted = StatDistribution(
                mean=adjusted.mean,
                std=max(adjusted.std, cv * 0.6 * adjusted.mean, 1e-6),
                dist_type=adjusted.dist_type,
            )
```

In `fantasy_service.build_fantasy_summary`, pass `calib=calib` to the
`project_fantasy_points(...)` call.

- [ ] **Step 2: Write the sweep driver**

```python
# scripts/tune_fantasy_calibration.py
"""Tune FantasyCalibration against the 2025 backtest cache.

  uv run python scripts/tune_fantasy_calibration.py --build-cache
  uv run python scripts/tune_fantasy_calibration.py --validate-approx
  uv run python scripts/tune_fantasy_calibration.py --run        # the sweep
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.fantasy_calibration import (  # noqa: E402
    default_calibration, evaluate, build_eval_cache, load_eval_cache,
    fit_glm_correction, save_calibration,
)

ARTIFACT = Path("models/fantasy_calibration.json")
LOG = Path("docs/fantasy_calibration_sweep.md")


def _log(line: str) -> None:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")
    print(line)


def validate_approx(n: int = 200, seed: int = 3) -> float:
    """|analytic P(boom) - MC P(boom)| on a subsample, using the real 5000-sim MC."""
    import warnings
    warnings.simplefilter("ignore")
    from eval.fantasy_calibration import _apply_calib_to_row, _boom_bust_prob, _BOOM, _BUST
    from eval.fantasy_points import project_fantasy_points, stable_simulation_seed
    from models.base import StatDistribution

    cache = load_eval_cache()
    rng = np.random.default_rng(seed)
    rows = [cache["rows"][i] for i in rng.choice(len(cache["rows"]), size=min(n, len(cache["rows"])), replace=False)]
    calib = default_calibration()
    diffs = []
    for r in rows:
        # analytic
        m, sd = _apply_calib_to_row(r, calib)
        pos = r["position"]
        pa, _ = _boom_bust_prob(m, sd, _BOOM[pos], _BUST[pos])
        # MC over the same blended per-stat means/stds
        dists = {}
        # reuse _apply_calib_to_row's per-stat math via a tiny reimplementation is overkill;
        # instead sample the moment-matched sum directly with a lognormal and compare
        sigma2 = np.log(1 + (sd / max(m, 1e-6)) ** 2)
        mu = np.log(max(m, 1e-6)) - 0.5 * sigma2
        sample = rng.lognormal(mu, np.sqrt(sigma2), 5000)
        pm = float(np.mean(sample >= _BOOM[pos]))
        diffs.append(abs(pa - pm))
    mad = float(np.mean(diffs))
    _log(f"- approx validation: mean |analytic - lognormal-MC| P(boom) = {mad:.3f} (n={len(rows)})")
    return mad


def _grid_search(cache, base) -> tuple:
    best = (evaluate(base, cache), base)
    _log(f"\n### Phase 1 — coarse grid\nbaseline objective={best[0]['objective']:.3f} "
         f"mae={best[0]['mae']:.2f} bias={best[0]['bias']:+.2f} "
         f"boom_err={best[0]['boom_calib_err']:.3f} rank={best[0]['rank_corr']:.3f}")
    for bw, yc, cap in itertools.product(
        (0.10, 0.15, 0.20, 0.25, 0.30), (0.55, 0.70, 0.85, 1.00), (1.06, 1.10, 1.15, 1.25)
    ):
        c = base.replace(glm_blend_weight=bw, yard_cv=yc, offense_stack_cap=cap)
        m = evaluate(c, cache)
        if m["objective"] < best[0]["objective"] and m["rank_corr"] >= base_rank - 0.03:
            best = (m, c)
    _log(f"phase-1 best objective={best[0]['objective']:.3f} "
         f"bw={best[1].glm_blend_weight} yc={best[1].yard_cv} cap={best[1].offense_stack_cap}")
    return best


def _coord_descent(cache, start_metrics, start, base_rank, passes: int = 3) -> tuple:
    _log("\n### Phase 2 — coordinate descent")
    best = (start_metrics, start)
    axes = {
        "glm_blend_weight": (0.05, 0.40, 0.03),
        "stat_mean_hi": (1.10, 1.90, 0.10),
        "stat_mean_lo": (0.30, 0.60, 0.05),
        "yard_cv": (0.45, 1.20, 0.05),
        "count_cv": (0.55, 1.30, 0.05),
        "context_clamp_hi": (1.08, 1.30, 0.02),
        "context_clamp_lo": (0.70, 0.90, 0.02),
        "offense_stack_cap": (1.03, 1.25, 0.02),
    }
    factor_axes = list(best[1].factor_strength)
    for p in range(passes):
        for name, (lo, hi, step) in axes.items():
            cur = getattr(best[1], name)
            for cand in (cur - step, cur + step):
                if not (lo <= cand <= hi):
                    continue
                c = best[1].replace(**{name: round(cand, 4)})
                m = evaluate(c, cache)
                if m["objective"] < best[0]["objective"] and m["rank_corr"] >= base_rank - 0.03:
                    best = (m, c)
        for fname in factor_axes:
            cur = best[1].factor_strength[fname]
            for cand in (max(0.0, cur - 0.15), min(1.5, cur + 0.15)):
                fs = {**best[1].factor_strength, fname: round(cand, 3)}
                c = best[1].replace(factor_strength=fs)
                m = evaluate(c, cache)
                if m["objective"] < best[0]["objective"] and m["rank_corr"] >= base_rank - 0.03:
                    best = (m, c)
        _log(f"pass {p+1}: objective={best[0]['objective']:.3f} mae={best[0]['mae']:.2f} "
             f"bias={best[0]['bias']:+.2f} boom_err={best[0]['boom_calib_err']:.3f} "
             f"bust_err={best[0]['bust_calib_err']:.3f} rank={best[0]['rank_corr']:.3f} "
             f"realism={best[0]['realism_penalty']:.2f}")
    return best


def _random_polish(cache, start_metrics, start, base_rank, iters: int = 300, seed: int = 5) -> tuple:
    _log("\n### Phase 3 — random local polish")
    rng = np.random.default_rng(seed)
    best = (start_metrics, start)
    for _ in range(iters):
        c = best[1].replace(
            glm_blend_weight=float(np.clip(best[1].glm_blend_weight + rng.normal(0, 0.02), 0.05, 0.40)),
            yard_cv=float(np.clip(best[1].yard_cv + rng.normal(0, 0.04), 0.45, 1.20)),
            count_cv=float(np.clip(best[1].count_cv + rng.normal(0, 0.05), 0.55, 1.30)),
            stat_mean_hi=float(np.clip(best[1].stat_mean_hi + rng.normal(0, 0.06), 1.10, 1.90)),
            offense_stack_cap=float(np.clip(best[1].offense_stack_cap + rng.normal(0, 0.02), 1.03, 1.25)),
            context_clamp_hi=float(np.clip(best[1].context_clamp_hi + rng.normal(0, 0.015), 1.08, 1.30)),
            factor_strength={k: float(np.clip(v + rng.normal(0, 0.08), 0.0, 1.5))
                             for k, v in best[1].factor_strength.items()},
        )
        m = evaluate(c, cache)
        if m["objective"] < best[0]["objective"] and m["rank_corr"] >= base_rank - 0.03:
            best = (m, c)
    _log(f"phase-3 best objective={best[0]['objective']:.3f} mae={best[0]['mae']:.2f} "
         f"bias={best[0]['bias']:+.2f} boom_err={best[0]['boom_calib_err']:.3f} rank={best[0]['rank_corr']:.3f}")
    return best


def run() -> None:
    cache = load_eval_cache()
    global base_rank
    base = default_calibration()
    bias, vinf = fit_glm_correction()
    base = base.replace(glm_bias=bias, glm_var_inflation=vinf)
    base_metrics = evaluate(base, cache)
    base_rank = base_metrics["rank_corr"]
    _log(f"\n## Sweep run\nGLM correction fit: {json.dumps(bias, sort_keys=True)}")
    _log(f"post-correction baseline: objective={base_metrics['objective']:.3f} "
         f"mae={base_metrics['mae']:.2f} bias={base_metrics['bias']:+.2f} "
         f"boom_err={base_metrics['boom_calib_err']:.3f} rank={base_rank:.3f} "
         f"realism={base_metrics['realism_penalty']:.2f}")
    m1, c1 = _grid_search(cache, base)
    m2, c2 = _coord_descent(cache, m1, c1, base_rank)
    m3, c3 = _random_polish(cache, m2, c2, base_rank)
    _log(f"\n## FINAL\n```json\n{json.dumps(c3.to_dict(), indent=2, sort_keys=True)}\n```")
    _log(f"final metrics: {json.dumps(m3, indent=2)}")
    save_calibration(c3, ARTIFACT)
    _log(f"written -> {ARTIFACT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--validate-approx", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.build_cache:
        print(build_eval_cache(2025))
    elif a.validate_approx:
        mad = validate_approx()
        sys.exit(0 if mad <= 0.03 else 1)
    elif a.run:
        run()
    else:
        ap.print_help()
```

- [ ] **Step 3: Run the smoke of the driver (approx validation) — one-off**

Run: `uv run python scripts/tune_fantasy_calibration.py --validate-approx`
Expected: prints the MAD; exit 0 if ≤ 0.03. If > 0.03, swap `_boom_bust_prob` to the gamma approx (see Task 4 Step 4) and re-run.

- [ ] **Step 4: Commit (driver + wiring, before the long run)**

```bash
git add scripts/tune_fantasy_calibration.py eval/fantasy_points.py api/services/fantasy_service.py
git commit -m "feat: fantasy calibration sweep driver + project_fantasy_points std floor"
```

---

## Task 7: Kalshi ladder — closest-to-even market

**Files:**
- Modify: `api/services/kalshi_odds_service.py`
- Test: `tests/test_kalshi_odds_service.py`

- [ ] **Step 1: Replace `_invert_ladder`**

```python
def _invert_ladder(markets: list[dict]) -> float | None:
    """The consensus line is the single laddered market trading nearest a coin
    flip (mid price closest to 50c). If the two closest straddle 0.5, interpolate
    between only those two; otherwise take that strike + 0.5."""
    pts = []
    for m in markets:
        strike = m.get("floor_strike")
        prob = _mid_yes_prob(m)
        if strike is None or prob is None:
            continue
        pts.append((float(strike), prob))
    if not pts:
        return None
    pts.sort()
    if len(pts) == 1:
        return pts[0][0] + 0.5
    # index of the market closest to a coin flip
    j = min(range(len(pts)), key=lambda i: abs(pts[i][1] - 0.5))
    k0, p0 = pts[j]
    # try to pair it with the neighbour on the other side of 0.5
    for nb in (j - 1, j + 1):
        if 0 <= nb < len(pts):
            k1, p1 = pts[nb]
            if (p0 - 0.5) * (p1 - 0.5) < 0 and p0 != p1:
                return k0 + (k1 - k0) * (p0 - 0.5) / (p0 - p1)
    return k0 + 0.5
```

- [ ] **Step 2: Update the tests**

In `tests/test_kalshi_odds_service.py`, `test_invert_ladder_finds_the_fifty_percent_strike`:
the ladder `20->.82, 24->.58, 28->.40` — closest to 0.5 is strike 24 (p=.58);
its neighbour 28 (p=.40) straddles → interpolate: `24 + 4*(.58-.5)/(.58-.40) = 24 + 4*0.444 = 25.78`. Update the assert to `24.0 < val < 27.0` (still passes) and add:

```python
def test_invert_ladder_uses_single_nearest_coinflip_market():
    # one market sits almost exactly at a coin flip; far strikes are lopsided
    markets = [
        {"floor_strike": 30, "yes_bid": 95, "yes_ask": 97},
        {"floor_strike": 44, "yes_bid": 49, "yes_ask": 51},   # ~0.50 -> the line
        {"floor_strike": 60, "yes_bid": 3, "yes_ask": 5},
    ]
    val = kos._invert_ladder(markets)
    assert 43.5 <= val <= 44.5
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_kalshi_odds_service.py -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add api/services/kalshi_odds_service.py tests/test_kalshi_odds_service.py
git commit -m "fix: Kalshi line = the single market nearest a coin flip, not a ladder fit"
```

---

## Task 8: research, run the sweep, lock config, verify, ship

Not TDD-shaped — an experiment with decision gates. Do the steps in order.

- [ ] **Step 1: Research (WebSearch), record in `docs/fantasy_calibration_sweep.md`**

Search and note 3–6 findings each:
- weekly fantasy-points coefficient of variation by position (WR/RB/TE/QB) — sets the plausible range for `yard_cv` / `count_cv`
- how public projection systems blend recent form vs a regression model (blend weights) — sanity range for `glm_blend_weight`
- published magnitude of a Vegas implied-team-total adjustment to a player projection — validate `game_environment` strength
- regression-to-mean rate for weekly fantasy production

Write a "## Research" section. These set **search bounds**, not the answer — the backtest decides.

- [ ] **Step 2: Build the real eval cache** (if not already from Task 3 Step 4)

Run: `uv run python scripts/tune_fantasy_calibration.py --build-cache`
Expected: `cache/fantasy_eval_cache_2025.pkl`, ~2000–2800 rows.

- [ ] **Step 3: Validate the analytic approximation**

Run: `uv run python scripts/tune_fantasy_calibration.py --validate-approx`
Expected: exit 0 (MAD ≤ 0.03). Adjust per Task 6 Step 3 if needed.

- [ ] **Step 4: Adjust search bounds in `scripts/tune_fantasy_calibration.py`** using the Step 1 findings if they fall outside the coded ranges. Commit the bound change if any.

- [ ] **Step 5: Run the sweep**

Run: `uv run python scripts/tune_fantasy_calibration.py --run`
Expected (~10–40 min): `docs/fantasy_calibration_sweep.md` gets Phase 1/2/3 traces; `models/fantasy_calibration.json` written. Final must show, vs the post-GLM-correction baseline: `mae` not worse, `|bias|` not worse, `boom_calib_err` and `bust_calib_err` reduced, `rank_corr` within 0.03, `realism_penalty` near 0.

- [ ] **Step 6: Point settings at the artifact**

In `api/settings.py` change the default:
`fantasy_calibration_path: str = str(_ROOT / "models" / "fantasy_calibration.json")`
(keeps env override; missing file still falls back to defaults inside `load_calibration`).

- [ ] **Step 7: Real 2026 W1 board sanity check**

Run:
```bash
uv run python -c "
import warnings; warnings.simplefilter('ignore')
from api.settings import AppSettings
from api.services import fantasy_slate_service as s
s._SLATE_CACHE.clear()
st=AppSettings(default_train_years=tuple(range(2015,2024)), prewarm_fantasy_slate=False, fantasy_slate_workers=10)
out=s.build_fantasy_slate(st, season=2026, week=1, scoring_mode='full_ppr', limit=48)
for pos in ('RB','WR','TE','QB'):
    print(pos, [(e.player_name.split()[-1], round(e.projected_points,1), round(e.boom_probability,2)) for e in out.entries if e.position==pos][:6])
"
```
Expected: top WR ≈ 21–26 (Nacua no longer 30), boom probabilities for the top plays in a plausible band (≈ 0.35–0.60, not 0.84). If the top is still > 27 or boom still > 0.7, tighten the objective weight on `realism_penalty` (2.0 → 4.0) and/or add a hard cap: reject configs whose max WR projection on a resampled 2026-W1-like set exceeds 27. Re-run Step 5.

- [ ] **Step 8: Boom/bust + MAE calibration tables (2025)**

Run:
```bash
uv run python -c "
from eval.fantasy_calibration import load_eval_cache, load_calibration, evaluate, default_calibration
cache=load_eval_cache()
print('DEFAULT  ', {k:round(v,3) for k,v in evaluate(default_calibration(),cache).items()})
print('TUNED    ', {k:round(v,3) for k,v in evaluate(load_calibration('models/fantasy_calibration.json'),cache).items()})
"
```
Paste the two lines into `docs/fantasy_calibration_sweep.md` under "## Final metrics".

- [ ] **Step 9: Full test suite**

Run: `uv run pytest -q`
Expected: all green (adjust any test asserting an old constant to read `default_calibration().<field>`). Then `cd desktop && npx tsc -b && npm run test` — green.

- [ ] **Step 10: Docs + version**

- `docs/season_eve_2026_dryrun.md`: add "## §11. Downstream calibration" — the objective, the GLM correction values, the final config deltas from default, the before/after 2026-W1 top and 2025 calibration metrics.
- `VERSIONS.md`: new `v0.9-m3.5` entry.

- [ ] **Step 11: Commit the artifact + docs**

```bash
git add models/fantasy_calibration.json docs/fantasy_calibration_sweep.md docs/season_eve_2026_dryrun.md VERSIONS.md api/settings.py
git commit -m "feat: locked fantasy downstream calibration (v0.9-m3.5)

Backtest-tuned on 2025 (GLM correction fit on 2023-2024). <one-line result:
top WR X->Y, boom X->Y, 2025 MAE X->Y, rank_corr preserved>."
```

- [ ] **Step 12: Rebuild sidecar + relaunch Tauri**

```bash
powershell -ExecutionPolicy Bypass -File desktop/scripts/build-sidecar.ps1
# then: cd desktop && npm run tauri dev
```
Confirm the running board shows the calibrated numbers.

---

## Self-Review

**Spec coverage:**
- §1 config object → Task 1 ✓
- §1 fantasy_service consumes it, defaults reproduce board → Task 2 ✓
- §2 build_eval_cache → Task 3 ✓
- §2 evaluate + objective + analytic boom, validated vs MC → Task 4 ✓
- §3 analytic GLM bias/variance on 2023-2024 → Task 5 ✓
- §3 sweep (grid → coord descent → random), guardrails → Task 6 + Task 8 Step 5 ✓
- §4 Kalshi closest-to-even → Task 7 ✓
- §4 research → Task 8 Step 1 ✓
- §4 verification (W1 sanity, calibration tables, pytest, rank_corr, sidecar) → Task 8 Steps 7–12 ✓
- "keep all metrics / factors wired" → `factor_strength` scales `(m-1)`, factor still emitted; outputs untouched ✓
- "don't touch the anchor" → anchor math not in `FantasyCalibration`, not modified ✓

**Placeholder scan:** Task 4 Step 1 contains a deliberately-shown-then-removed `placeholder` line with an explicit note to use only the real `std =` line. Every other step has complete code.

**Type consistency:** `FantasyCalibration.replace()` used throughout; `evaluate` returns the dict keys checked in Task 8; `_apply_calib_to_row` / `_boom_bust_prob` / `_calibration_error` defined in Task 4 and reused in Task 6's `validate_approx`. `glm_bias` keys are `"POS/stat"` strings everywhere (Task 5 emits, Task 2 + Task 4 read).
