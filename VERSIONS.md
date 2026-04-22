# Version History

---

## v0.0 - 2026-04-22

**Initial repo setup.**

- Created project file tree (data, models, eval, llm, ui, docs, cache)
- Added implementation plan with version checkpoints
- Added stub files for all planned modules
- Established VERSIONS.md tracking

---

## v0.1 - 2026-04-22

**nflverse data ingestion + parquet cache layer.**

- Implemented `data/nflverse_loader.py` with 10 loader functions: `load_weekly`, `load_pbp`, `load_seasonal`, `load_schedules`, `load_team_desc`, `load_ngs`, `load_injuries`, `load_snap_counts`, `load_rosters`, `load_qbr`
- Cache layer: pyarrow parquet, 24h mtime staleness, `force_refresh` bypass, per-dataset filenames with sorted year key (avoids collision on non-contiguous year lists)
- Year constants: `TRAIN_YEARS` (2015-2024), `HOLDOUT_YEARS` ([2025]), `ALL_YEARS` (1999-2025)
- `DOME_TEAMS` frozenset (9 teams: ARI, ATL, DAL, DET, HOU, IND, LV, MIN, NO) + `is_dome()` helper
- Package `__init__.py` added to data, models, eval, llm, ui
- 35 tests (31 fast mocked + 4 slow real-API), all passing
- Dependencies: nfl-data-py 0.3.2, pandas 3.0.2, pyarrow 24.0, scipy, scikit-learn, pytest

---

## v0.2 - 2026-04-22

**Position models (QB, RB, WR/TE) + game simulation.**

- `models/base.py`: `StatDistribution` dataclass with `prob_over(line) -> float` supporting gamma, poisson, tweedie, and normal distributions
- `models/qb.py`: `QBModel` - Gamma GLM per stat (passing_yards, passing_tds, interceptions, completions), empirical Bayes shrinkage k=8, 4-game rolling features
- `models/rb.py`: `RBModel` - Tweedie GLM for rushing_yards, Poisson for carries/rushing_tds
- `models/wr_te.py`: `WRTEModel` - Poisson for receptions/receiving_tds, Gamma for receiving_yards; handles WR + TE positions
- `models/game_sim.py`: `simulate_game()` Monte Carlo (default 10k sims), normal score distributions from spread/total, returns `GameSimResult` with score arrays + win/over probabilities
- All models share interface: `fit(years)`, `predict(player_id, week, season, opp_team) -> dict[str, StatDistribution]`, `save(path)`, `load(path)` via joblib
- `tests/test_models.py`: 9 tests, all passing

---

## v0.2.1 - 2026-04-22

**Review checkpoint: Steps 1–2 verification, Step 3 status, and `eval/prop_pricer` completed.**

### Step 1 (nflverse ingest + cache) — review

**Done vs plan:** `data/nflverse_loader.py` provides ten cached loaders (weekly, pbp, seasonal, rosters, schedules, team_desc, ngs×3 stat types, injuries, snap_counts, qbr) with pyarrow parquet, 24h staleness, `force_refresh`, and year-suffixed cache keys. Smokes: `tests/test_nflverse_loader.py` (31 fast + 4 slow), total **62** project tests after this release.

**Gaps / issues:**

1. **Default year span:** `load_*` defaults use `TRAIN_YEARS` (2015–2024), not `ALL_YEARS` (1999–2025). Full Step‑1 “1999–2025 parquet” one-shot requires `years=ALL_YEARS` (or a dedicated one-time ingest path); otherwise cache only covers the training window you request.
2. **Plan vs API name:** The plan text mentions `import_rosters()`; the implementation uses `nfl.import_weekly_rosters()`, which is the current nfl_data_py entry point for week-level rosters.
3. **Optional sources:** `import_combine_data` / `import_draft_picks` (listed in the plan as available) are not wrapped; add only if features need them.

### Step 2 (models + backtest) — review

**Done vs plan:** `models/base.py` (`StatDistribution`, `prob_over`), `models/qb.py`, `models/rb.py`, `models/wr_te.py`, and `models/game_sim.py` exist with the shared `fit` / `predict` / `save` / `load` pattern. `tests/test_models.py` covers unfitted fallbacks, one mocked `fit` for QB, and game sim invariants.

**Gaps / issues:**

1. **Walk-forward CV and metrics:** The plan’s exit criterion — walk-forward cross-validation by season with metrics recorded — is **not implemented** (no per-season backtest loop, no logged error metrics in-repo).
2. **Defensive / opponent context:** `predict(..., opp_team=...)` is accepted but not used in feature construction, so there is no opponent-adjusted signal yet.
3. **“Four position groups”:** The plan’s QB / RB / WR+TE and Monte Carlo are present; kicker and DEF are explicitly out of MVP scope in “Resolved Scope Decisions.”

### Step 3 (prop pricing + calibration) — completion estimate: **~55%**

| Criterion (plan) | Status |
| ---------------- | ------ |
| `eval/prop_pricer.py` — fair price, edge, calibrator | **Done** (isotonic + Platt, `implied_prob`, `fair_price_to_american`, `reliability_diagram`, `price_prop`, joblib `save`/`load`) |
| `tests/test_prop_pricer.py` | **Done** (18 tests) |
| Calibration fit on **2025 closing lines** | **Not done** (unit tests use synthetic data only) |
| Reliability plot **on 2025 hold-out**; diagram saved under `docs/` | **Not done** |
| Coefficients saved for production use | **Supported in code**; no fitted artifact from real lines committed |

**Dependencies:** `matplotlib` added for optional reliability figure export.

**Other:** `tests/test_prop_pricer.py` — roundtrip tolerance for `fair_price_to_american` ↔ `implied_prob` set to `0.0005` (integer American odds cannot match arbitrary probabilities within `1e-4`).

---
