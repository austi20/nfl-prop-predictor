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
