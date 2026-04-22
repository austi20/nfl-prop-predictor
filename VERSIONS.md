# Version History

Note: entries are listed newest first and oldest last.

---

## v0.2.5 - 2026-04-22

**Commit + push snapshot: accuracy-focused modeling update with calibration tooling retained but deferred.**

- Recorded the user-directed scope change: player props and Step 3 calibration are **deferred for now** while the project focuses on improving base model accuracy
- Added walk-forward and holdout evaluation tooling in `eval/model_backtest.py` with generated artifacts in `docs/walk_forward_metrics.*` and `docs/holdout_metrics.*`
- Added a Step 3 calibration pipeline scaffold in `eval/calibration_pipeline.py` that can fit/save calibrators and reliability artifacts once a historical closing-line file is available
- Added a minimal The Odds API historical client in `data/odds_client.py` for future calibration/replay work when a valid paid historical source is available
- Fixed 2025 weekly data loading by falling back to official nflverse direct-release files in `data/nflverse_loader.py`
- Normalized weekly schema differences from direct-release files (`passing_interceptions`, `sacks_suffered`, `sack_yards_lost`, `team`) so downstream modeling/evaluation code stays consistent
- Improved model features using existing nflverse weekly data:
  - QB: `passing_air_yards`, `passing_epa`, `dakota`
  - RB: `rushing_epa`
  - WR/TE: `target_share`, `air_yards_share`, `wopr`, `receiving_epa`
- Added and updated test coverage for loader fallbacks, model backtests, calibration pipeline, odds client, and prop pricer behavior
- Verification: `72 passed, 4 deselected` via `uv run pytest -q`

**Current project note:** calibration is **not completed** in this version. The calibration code path exists, but historical player prop closing lines are intentionally not the active priority right now.

---

## v0.2.4 - 2026-04-22

**Scope change: defer props/calibration work and focus on model accuracy.**

- By user direction, Step 3 calibration work against historical player prop lines is **paused for now**
- Historical player props are **intentionally being skipped** while the project focuses on improving base model accuracy first
- Added official nflverse direct-release fallback in `data/nflverse_loader.py` so 2025 weekly player data loads even when `nfl_data_py` fails for that season
- Normalized direct-release weekly columns (`passing_interceptions` -> `interceptions`, `sacks_suffered` -> `sacks`, `team` -> `recent_team`) so holdout evaluation stays consistent with the rest of the codebase
- Improved model feature inputs using already-available nflverse weekly fields:
  - QB: `passing_air_yards`, `passing_epa`, `dakota`
  - RB: `rushing_epa`
  - WR/TE: `target_share`, `air_yards_share`, `wopr`, `receiving_epa`
- Regenerated walk-forward and 2025 holdout metrics in `docs/walk_forward_metrics.*` and `docs/holdout_metrics.*`
- Verification: `72 passed, 4 deselected` via `uv run pytest -q`

**Important note:** calibration against historical prop closing lines is **not completed** in this version and is **not the active priority right now**. The active priority is improving core model accuracy without depending on player prop data.

---

## v0.2.3 - 2026-04-22

**Data-backed Step 2 reporting artifacts generated.**

- Ran `uv run python -m eval.model_backtest` and generated `docs/walk_forward_metrics.json` plus `docs/walk_forward_metrics.md`
- Cached historical weekly nflverse data for 2015-2024 at `cache/weekly_2015-2016-2017-2018-2019-2020-2021-2022-2023-2024.parquet`
- Added holdout reporting support to `eval/model_backtest.py` and graceful blocked-report output when the configured holdout season is unavailable from the upstream data source
- Added holdout-path coverage in `tests/test_model_backtest.py`
- Verification: `33 passed` for targeted model/backtest/pricer tests and `61 passed, 4 deselected` for the full default pytest suite

**Step 2 status on 2026-04-22:** walk-forward CV metrics are now logged in-repo. The configured 2025 holdout remains blocked because `nfl_data_py` in this environment returns `HTTP Error 404: Not Found` for weekly 2025 data, and that blocked state is recorded in `docs/holdout_metrics.json` and `docs/holdout_metrics.md`.

---

## v0.2.2 - 2026-04-22

**Walk-forward CV harness for Step 2 + local verification cleanup.**

- Added `eval/model_backtest.py` with a simple walk-forward backtest flow for `QBModel`, `RBModel`, and `WRTEModel`
- Reports save to `docs/walk_forward_metrics.json` and `docs/walk_forward_metrics.md` via `python -m eval.model_backtest`
- `models/qb.py`, `models/rb.py`, and `models/wr_te.py` now accept an optional preloaded weekly DataFrame in `fit(...)` so the evaluator can reuse one historical load instead of reloading per season
- `eval/prop_pricer.py` now forces Matplotlib's `Agg` backend for headless reliability-plot export
- Added `tests/test_model_backtest.py` and a repo-local pytest temp fixture in `tests/conftest.py`
- Pytest config now scopes collection to `tests/`, skips `slow` tests by default, and keeps pytest cache under `tmp/`
- Verification: `61 passed, 4 deselected` via `uv run pytest -q`

**Remaining Step 2 gap:** the backtest runner is implemented, but no real walk-forward metrics artifact is committed yet because `cache/` is currently empty in this workspace. After historical data is populated, run `uv run python -m eval.model_backtest` to generate the docs reports.

---

## v0.2.1 - 2026-04-22

**Review checkpoint: Steps 1â€“2 verification, Step 3 status, and `eval/prop_pricer` completed.**

### Step 1 (nflverse ingest + cache) â€” review

**Done vs plan:** `data/nflverse_loader.py` provides ten cached loaders (weekly, pbp, seasonal, rosters, schedules, team_desc, ngsÃ—3 stat types, injuries, snap_counts, qbr) with pyarrow parquet, 24h staleness, `force_refresh`, and year-suffixed cache keys. Smokes: `tests/test_nflverse_loader.py` (31 fast + 4 slow), total **62** project tests after this release.

**Gaps / issues:**

1. **Default year span:** `load_*` defaults use `TRAIN_YEARS` (2015â€“2024), not `ALL_YEARS` (1999â€“2025). Full Stepâ€‘1 â€œ1999â€“2025 parquetâ€ one-shot requires `years=ALL_YEARS` (or a dedicated one-time ingest path); otherwise cache only covers the training window you request.
2. **Plan vs API name:** The plan text mentions `import_rosters()`; the implementation uses `nfl.import_weekly_rosters()`, which is the current nfl_data_py entry point for week-level rosters.
3. **Optional sources:** `import_combine_data` / `import_draft_picks` (listed in the plan as available) are not wrapped; add only if features need them.

### Step 2 (models + backtest) â€” review

**Done vs plan:** `models/base.py` (`StatDistribution`, `prob_over`), `models/qb.py`, `models/rb.py`, `models/wr_te.py`, and `models/game_sim.py` exist with the shared `fit` / `predict` / `save` / `load` pattern. `tests/test_models.py` covers unfitted fallbacks, one mocked `fit` for QB, and game sim invariants.

**Gaps / issues:**

1. **Walk-forward CV and metrics:** The planâ€™s exit criterion â€” walk-forward cross-validation by season with metrics recorded â€” is **not implemented** (no per-season backtest loop, no logged error metrics in-repo).
2. **Defensive / opponent context:** `predict(..., opp_team=...)` is accepted but not used in feature construction, so there is no opponent-adjusted signal yet.
3. **â€œFour position groupsâ€:** The planâ€™s QB / RB / WR+TE and Monte Carlo are present; kicker and DEF are explicitly out of MVP scope in â€œResolved Scope Decisions.â€

### Step 3 (prop pricing + calibration) â€” completion estimate: **~55%**

| Criterion (plan) | Status |
| ---------------- | ------ |
| `eval/prop_pricer.py` â€” fair price, edge, calibrator | **Done** (isotonic + Platt, `implied_prob`, `fair_price_to_american`, `reliability_diagram`, `price_prop`, joblib `save`/`load`) |
| `tests/test_prop_pricer.py` | **Done** (18 tests) |
| Calibration fit on **2025 closing lines** | **Not done** (unit tests use synthetic data only) |
| Reliability plot **on 2025 hold-out**; diagram saved under `docs/` | **Not done** |
| Coefficients saved for production use | **Supported in code**; no fitted artifact from real lines committed |

**Dependencies:** `matplotlib` added for optional reliability figure export.

**Other:** `tests/test_prop_pricer.py` â€” roundtrip tolerance for `fair_price_to_american` â†” `implied_prob` set to `0.0005` (integer American odds cannot match arbitrary probabilities within `1e-4`).

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

## v0.0 - 2026-04-22

**Initial repo setup.**

- Created project file tree (data, models, eval, llm, ui, docs, cache)
- Added implementation plan with version checkpoints
- Added stub files for all planned modules
- Established VERSIONS.md tracking

---
