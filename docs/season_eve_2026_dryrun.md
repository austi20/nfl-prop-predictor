# Season-Eve 2026 Dry Runs

**Date:** 2026-09-08 (NFL 2026 regular season opens 2026-09-09).
**Scope:** unfreeze the project for the 2026 season — bring data current, and
exercise the training + paper-execution pipelines end to end on the freshest
available real data.

## Data reality check

nflverse has **no 2026 player-level data yet** — the `stats_player_week_2026`
release lands only after Week 1 games are played. nflverse also carries **no
preseason player box scores, ever** (0 `_pre_` files in the entire release
history), so "train on preseason games" is not possible from this project's
data sources. Live for 2026 today: full schedule (272 games), Week-1 rosters,
early injury reports. The freshest *complete* season is **2025**, which is what
every dry run below targets.

## What changed

| Area | Change |
|---|---|
| `data/nflverse_loader.py` | `ALL_YEARS` -> ..2026. `TRAIN_YEARS` (2015-2024) / `HOLDOUT_YEARS` ([2025]) left as-is — they must stay disjoint (`model_backtest` / `replay_pipeline` treat HOLDOUT as the out-of-sample test set for a fit on TRAIN). 2026 stays out of weekly-loading lists (no data / 404). |
| `scripts/prefetch_training_cache.py` | schedule + injury windows extended to 2026. |
| caches | refreshed: weekly 217,490 rows (2014-2025), schedules incl. 2026, injuries/rosters through 2026. |
| `docs/training/synthetic_props_training.csv` | regenerated from refreshed cache: **144,562 rows** (2019-2025), all eligible; 2025 now fully resolved (21,108 rows, 0 null outcomes). |
| `scripts/generate_synthetic_props.py`, `scripts/capture_preseason_baseline.py` | added repo-root `sys.path` bootstrap — both were un-runnable as documented (`ModuleNotFoundError: data`). |
| `scripts/capture_preseason_baseline.py` | `compute_baseline_rows()` was a stub returning `[]`; now fits the locked GLMs and scores them (first real run — the modernization plan's "fill in once preseason data lands"). |
| `api/trading/paper_adapter.py` | `RealisticPaperAdapter` no longer logs the misleading "fake paper adapter active" line via the shared parent `__init__`. |
| `.gitignore` | `docs/audit/`, `docs/training/rerun_*/`, Week-1 signal scratch. |
| `scripts/dry_run_execution.py` *(new)* | drives `/api/execution/paper/submit` end to end — the only exercise of ExecutionService -> mapper -> risk -> paper adapter -> ledger together. |
| `scripts/dry_run_week1_2026.py` *(new)* | builds the real Week-1 slate, prices it, paper-submits it. |
| `models/{qb,rb,wr_te}.py` | **§5** — drop `is_home` (constant / collinear); cold-start GLM+trailing blend + clamp; `future_row`-gated spread recalibration. Historical path byte-for-byte unchanged. |
| `models/dist_family.py` | `residual_cv` + `recalibrate_spread` helpers for §5 spread calibration. |
| `data/nflverse_loader.py` | `ALL_YEARS` -> ..2026; `_fetch_weekly_direct` skips a 404 (unpublished) year instead of crashing, so a 2026 request works before Week 1. |
| `api/settings.py` | `use_future_row` **False -> True** (upcoming path fixed in §5). |
| `api/services/{evaluation,fantasy}_service.py` | `scoring_weekly()` widens the fit + history window to every complete season through the scored one (a 2026 request no longer trains only through ~2023). |
| `tests/test_predict_with_future_row.py` | fixture widened to 2 seasons so the 27-feature GLM is not underdetermined after the `is_home` drop. |

## 1. Training accuracy — locked config, refreshed data (`eval/model_backtest.py`)

Locked H5 per-position config. Walk-forward (fit on prior seasons only) and a
disjoint 2025 holdout (fit 2015-2024). **Every stat's MAE and RMSE improved vs
the April baseline** — from the extra data volume + small upstream nflverse
corrections, not from leakage (both runs use the same disjoint setup).

Holdout = 2025 (fit 2015-2024):

| stat | MAE (Apr -> now) | RMSE (Apr -> now) | bias now |
|---|---|---|---|
| qb passing_yards | 80.26 -> **79.40** | 101.58 -> **100.23** | +24.8 |
| qb completions | 6.61 -> **6.59** | 8.62 -> **8.50** | +1.87 |
| rb rushing_yards | 24.55 -> **22.67** | 32.08 -> **30.39** | +1.08 |
| rb carries | 4.85 -> **4.23** | 5.81 -> **5.26** | +0.44 |
| wr_te receptions | 1.66 -> **1.52** | 2.07 -> **1.94** | +0.26 |
| wr_te receiving_yards | 22.55 -> **21.47** | 28.73 -> **27.94** | +4.39 |

Full tables: `docs/holdout_metrics.md`, `docs/walk_forward_metrics.md`.

**Note:** QB `passing_yards` carries a persistent **positive bias (~+25 yd/game
on 2025)** — the mean model leans high. Pre-existing, not a regression, and the
same direction as the section-5 forward-scoring blowup.

## 2. Preseason baseline — uncalibrated GLM probability quality

`docs/preseason_baseline_2026.md` (locked GLMs, fit 2018-2024, scored on 2025
synthetic props). Frozen reference for the P5 calibration gate.

| | best | worst |
|---|---|---|
| log_loss | wr_te receiving_tds **0.489** | **rb carries 2.35** |
| brier | wr_te receiving_tds **0.157** | **rb carries 0.456** |

**`rb/carries` is badly miscalibrated** — log_loss 2.35 / brier 0.46 is worse
than an uninformed 0.693 / 0.25. The model prices carries over/under with
overconfident probabilities. Point accuracy for carries is *fine* (MAE 4.2), so
this is a tail/distribution problem, i.e. exactly what `use_calibration`
(deferred until real Kalshi lines) is meant to fix. Every other stat lands
0.49-0.80 log_loss — weak but not broken.

## 3. Paper-trade replay 2025 (`eval/replay_pipeline.py`)

`docs/paper_trade_summary_2025.md` — 18,801 singles vs synthetic surrogate
lines: **ROI +7.6%, win rate 56.4%**. Best `receiving_tds` (+51%), worst
`carries` (-19%). This measures *model vs. naive trailing-mean lines* — it is
**not** a real-market edge estimate.

## 4. Execution stack end to end (`scripts/dry_run_execution.py`)

Fed 1,500 real 2025 replay picks through `/api/execution/paper/submit`:
**1,500/1,500 filled**, 361 positions, 1,500 order events, `docs/audit/`
JSONL + portfolio snapshot written. The full chain works:
`NormalizedPick -> Signal -> ExecutionIntent (mapper) -> ExposureRiskEngine ->
RealisticPaperAdapter -> InMemoryPortfolioLedger`.

Observations (not blockers):
- Paper ledger has **no bankroll** — `cash_balance` just goes negative by net
  contract cost (`InMemoryPortfolioLedger` starts at 0). Fine for a paper
  ledger; a funded-account model is a modernization item.
- Synthetic `market_id` is `PAPER-<player8>-<stat4>` — it does **not** encode
  week, so multiple weeks of the same player+stat collapse to one position.

## 5. 2026 Week-1 slate dry run — blocker found, then fixed

The first pass built the real Week-1 slate and paper-submitted it (plumbing
worked), but every projection was garbage — QB passing yards of 600-1000+. A
systematic-debugging pass (`docs/season_eve_2026_dryrun.md` history / commit
messages) found and fixed four coupled defects in the `future_row` / upcoming
scoring path (`models/{qb,rb,wr_te}.py`, `api/services/`):

| Defect | Fix | Verification |
|---|---|---|
| **`is_home` is a constant 0.5** in real nflverse data (no home/away column), so it is collinear with the intercept and the unregularised GLM gives it an arbitrary coefficient (+2.0 on passing_yards). Feeding a real 0/1 value on an upcoming game swings the mean `e^coef` ≈ 3-7×. | Drop `is_home` from all three feature sets. | Historical-path predictions **numerically identical** (constant absorbed by the refit intercept); `model_backtest` holdout MAE unchanged to 3 dp. |
| **Week-1 shrinkage collapse** — no same-season prior weeks ⇒ `n/(n+k)` with `n=0` ⇒ every projection = league prior. | Cold-start blend: weight the GLM point estimate against the player's own **trailing average** (`roll_<stat>`), trusting the GLM more as the prior-season game count grows (capped at 10); no history ⇒ league prior. | Week-1 slate proj / recent-form ratio: median **0.93**, p90 1.4, 5% outside [0.5, 2.0] (was 15%). |
| **GLM extrapolation** to absurd means for low-sample / off-manifold players (Herbert 552 yд / 74 att). | Clamp the cold-start mean to `[0.4, 1.8] × trailing average`. | max proj / recent-form ratio **1.88** (was 33×). |
| **Distribution over-dispersion** — the NegBin / decomposed-MC layers inflate spread ~1.3-2× (carries std 11 vs empirical 7; receptions 5 vs 2.4) because the training pool mixes starters with cameo appearances ⇒ mushy `P(over)` ≈ 0.5. | `recalibrate_spread()` in `models/dist_family.py`: rescale each stat's distribution to a robust residual CV measured at fit time. **Gated to the `future_row` path only.** | `P(over)` now spans ~0.32-0.64 across a spot slate instead of clustering at 0.5. |

All four fixes are **gated so the historical / backtest / replay / preseason-
baseline path is byte-for-byte unchanged** (`docs/holdout_metrics.md`,
`docs/preseason_baseline_2026.md` reproduce exactly). Only `future_row` scoring
changed.

**`use_future_row` is now `True`** and the app prices the 2026 slate:
`POST /api/props/evaluate` for a Week-1 2026 prop returns a realistic mean and
an informative probability (e.g. Mahomes passing yards mean ≈ 290, `P(over
239.5)` ≈ 0.64). Supporting changes: `data/nflverse_loader.py` tolerates the
missing 2026 weekly release (skips the 404 year instead of crashing);
`api/services/evaluation_service.py::scoring_weekly` widens the fit + history
window to every complete season through the one being scored (a 2026 request
was previously training only through ~2023).

### Known residual gap — mean bias in a shifted environment

The locked GLMs are calibrated to a **2018-2024** average. Measured on 2025
holdout, they over-project QB passing yards by **~+24/game** and receiving
yards by ~+4 (`calib_check`: PIT mean ~0.43, PIT-KS 0.18-0.38 for yardage
stats). The cause is temporal: 2025 was a lower-output passing environment than
the training window, and the models cannot self-correct from in-sample stats
(their training-set bias is ~0). The cold-start blend pulls upcoming
projections ~25-30% toward 2025 recent form, which dampens but does not remove
this. A full fix needs a bias + variance calibration layer fit on held-out
actuals (or the deferred real-Kalshi-quote path) — it is **not** something to
land the night before kickoff. The point-estimate accuracy (MAE ~79 passing
yд) and the paper-execution economics are unaffected.

## Deferred / not done

## Deferred / not done

- **Full 144-config walk-forward grid re-validation** — the locked per-stat
  config is human-reviewed (Phase H5); re-running the grid to re-confirm it is
  ~hours and low value. Run off-hours if desired:
  `uv run python scripts/train_loop.py --out-dir docs/training/rerun_YYYY`.
- **Probability calibration + the §5 mean-bias gap** — still gated on real
  Kalshi quote capture (or a held-out-actuals calibration layer). `rb/carries`
  (uncalibrated log-loss 2.35) and the ~+24yd QB passing bias on shifted-
  environment seasons are the strongest arguments for building it. The §5 fixes
  make upcoming projections *realistic* and the probabilities *informative*;
  they do not make them *calibrated*.
- **Live weather forecast** (`use_live_forecast`) — archive stops at 2025;
  needs the Open-Meteo forecast path for 2026 games. Models are `use_weather=
  False` so not blocking.
- **Modernization Phases 2-7** (`docs/modernization_plan.md`) — untouched;
  the uncommitted Phase 0-1 SQL-ledger / kill-switch scaffold in the working
  tree stays uncommitted (self-contained, unwired, out of scope here).
