# Version History

Note: entries are listed newest first and oldest last.
Note: versioning follows `v0.x` or `v0.x.y`, where `x` maps to the numbered plan step in `docs/plan.md` for the current active work phase and optional `.y` is reserved for sub-updates within that active step. If work is currently under Step 4, then related fixes or improvements still version as `v0.4.y` until the active step changes.

---

## v0.9-m3.5 - 2026-09-09

**Downstream calibration — deflate the elite-tail fantasy projections.**

The 2026 Week-1 board projected the top WR at 30.4 pts / 0.84 boom. The trailing
anchor (~21) was fine; the inflation was all downstream — GLM blend, a collinear
"good offense" factor stack, and distributions too tight for weekly variance.
Detail: `docs/season_eve_2026_dryrun.md` §11, `docs/fantasy_calibration_sweep.md`.

- **`FantasyCalibration`** (`eval/fantasy_calibration.py`) — every knob downstream
  of the anchor in one frozen object; defaults reproduce the old board exactly;
  locked values in `models/fantasy_calibration.json`, path in
  `AppSettings.fantasy_calibration_path` (missing file → defaults).
- **2025 backtest sweep** — precompute-once cache (2741 player-weeks, all four
  positions), per-position-balanced objective (MAE + |bias| + boom/bust
  calibration + realism − rank corr), grid → coordinate descent → random polish,
  with a no-per-position-rank-regression guardrail. Shared GLMs **not** refit;
  props / replay / preseason-baseline / model-backtest byte-identical.
- **Analytic GLM correction** (`fit_glm_correction`, fit on 2023-2024, cached to
  `models/fantasy_glm_correction.json`) — `median(actual)/median(pred)` per
  (position, stat), clipped [0.6, 1.4]. TD-rate stats all hit the 0.6 floor.
- **Result** — 2025 (pos-balanced): objective 3.30 → 2.58, MAE 5.12 → 4.99,
  |bias| 0.48 → 0.27, rank corr 0.574 → 0.595 (every position up). 2026 W1:
  Nacua 30.4 / 0.84 → **22.5 / 0.61**. Every context factor still computed and
  rendered; `factor_strength` only scales its `(multiplier − 1)`.
- **Kalshi line** — `_invert_ladder` now takes the single laddered market trading
  nearest a coin flip (the real line), not a fit across every incremental strike.

Backend 410+ pass. Files: `eval/fantasy_calibration.py` (new),
`scripts/{tune,verify}_fantasy_calibration.py` (new),
`models/fantasy_{calibration,glm_correction}.json` (new),
`api/services/{fantasy_service,kalshi_odds_service}.py`, `eval/fantasy_points.py`,
`api/settings.py`.

---

## v0.9-m3.4 - 2026-09-09

**Situational factors — wire the "team / coaching / opponent / weather" goal.**

Projections were ~80% "player's own recent form". Ten context factors now feed
the fantasy projection (product of non-injury nudges clamped to [0.75, 1.25]).
Detail: `docs/season_eve_2026_dryrun.md` §10.

- **Home/away** back in the GLM — `data/game_context.attach_is_home()` joins
  the schedule's home/away onto the weekly frame; `is_home` restored to
  `feature_cols` in qb/rb/wr_te; refit, holdout MAE flat.
- **Game environment / game script** — schedule `total_line`/`spread_line` →
  implied team points + favourite/underdog run-pass tilt.
- **Opponent matchup** — fantasy points allowed to the position vs league, on
  every scoring stat (`_rows_before()` spans 2 seasons so Week 1 works).
- **Weather** — `data/weather.load_forecast()` implemented against Open-Meteo
  (free, no key); `_weather_factors()` trims passing in wind/precip/cold.
  `use_live_forecast` default True.
- **Coaching** (schedule coach → career PPG, outliers only) and **rest**
  (bye / short week).
- **Usage trend** — `data/usage.py`: snap % (nflverse snap counts + `import_ids`
  crosswalk) and NGS air-yards share, recent-3 vs games-4-8-back.
- **Injury factor fixed** — "Did Not Participate" now matches; game-status vs
  practice-status split; Out 0.20→0.05; self-fetches the season parquet.
- **QB-support / position-group** factors fixed — were neutral all of Week 1
  (only looked at the current season).
- **News gate** — `data/news.py` ESPN public news API; keyword scan for QB
  shakeup / coordinator firing, hourly cache, no LLM in the loop.
- **Kalshi** — `api/trading/kalshi/client.py` real market-data reads (signing
  salt fixed 32); `kalshi_odds_service.nfl_game_lines()` inverts the
  `KXNFLTOTAL` ladder to an implied total and overrides the schedule total when
  the market is priced (thin pre-kickoff, so W1 uses the schedule line).

New: `data/{game_context,usage,news}.py`, `api/services/kalshi_odds_service.py`.
Tests: ~40 new across `test_{game_context,fantasy_context_factors,usage,
news_factor,kalshi_odds_service}.py`. `docs/holdout_metrics.md` regenerated.

## v0.9-m3.3 - 2026-09-09

**Fantasy-slate: kill the request pile-up, parallelise the build.**

A user report — the *This Week* board stuck on "Building…" for 30 min — traced
to unbounded concurrent recomputation. Detail: `docs/season_eve_2026_dryrun.md`
§8.

- **Concurrency guard.** `build_fantasy_slate` takes a process-wide lock
  (double-checked cache). The startup prewarm waits; an HTTP handler that finds
  a build in progress returns a 200 body with `ready=false` instead of parking
  a threadpool thread. `FantasySlateResponse.ready` added.
- **GUI fetch hygiene.** `retry=false`, no refetch on window focus / reconnect,
  and the fetch forwards React Query's `AbortSignal` so superseded requests
  cancel. The board polls every 8 s while `!ready`.
- **Parallel projection.** The per-player loop fans out across a spawn process
  pool at ~70 % of cores (`NFL_APP_FANTASY_SLATE_WORKERS`, 1 = serial). Output
  byte-identical to serial; 2.4x at 6 workers on a loaded box. `api/sidecar.py`
  pins BLAS to one thread/process and adds `multiprocessing.freeze_support()`;
  pool failure falls back to serial.
- Tests: `test_fantasy_slate_service.py` 4 → 8. Backend 376 pass, desktop
  `tsc -b` + 17 vitest green.

## v0.9-m3.2 - 2026-09-09

**Fantasy-first GUI + week-level fantasy projection board.**

The app is fantasy-football-first (props + Kalshi trading secondary); the
desktop shell did not reflect that and had no fantasy view. Full detail:
`docs/season_eve_2026_dryrun.md` §8.

- **Desktop reframe.** Nav is now `This Week · Props · Parlays ·
  Trading (Paper)`, brand mark "NFL Fantasy". The betting dashboard moved
  `/` → `/props` (content unchanged). New landing view
  `desktop/src/routes/this-week-page.tsx` — ranked Week-N board:
  projected / floor / ceiling / boom% per player, position + scoring
  (full/half PPR) + week filters, row links to player detail.
- **`GET /api/fantasy/slate/{season}?week=&scoring=&limit=`**
  (`api/services/fantasy_slate_service.py`, `+FantasySlate{Entry,Response}`).
  Schedule + roster enumeration → cheap trailing-FP prescore →
  `_MIN_TRAILING_GAMES=3` gate → per-team depth cap → per-position budget
  slice of `limit` → full `build_fantasy_summary` on that union only.
  Response cached per `(season, week, scoring, limit)`.
- **Startup prewarm.** `build_fantasy_summary` is a 5000-sim MC per player so
  a cold slate is ~4-5 min; the sidecar builds the Week-1 board on a daemon
  thread at boot (`prewarm_current_slate`, `AppSettings.prewarm_fantasy_slate`,
  default on, off for tests/scripts, env `NFL_APP_PREWARM_FANTASY_SLATE=0`).
  GUI requests `limit=48` to match the prewarm cache key.
- 2026-W1 sanity (full PPR): Bijan 18.5 / Henry 17.5 / Nacua 25.7 /
  St. Brown 21.9 / McBride 17.6. QB still clusters high (16-21) and
  thin-sample rookies leak in — documented residual, fixed by the post-Week-1
  calibration layer.
- Tests: `tests/test_fantasy_slate_service.py` (4). Backend **376 pass**,
  1 skipped, 5 deselected. Desktop `tsc -b` clean, **17 vitest pass**.

## v0.9-m3.1 - 2026-09-08

**Upcoming-game scoring fixed; app prices the 2026 slate. `use_future_row` on.**

The v0.9-m3 Week-1 dry run flagged the `future_row` path as a blocker. A
systematic-debugging pass fixed it. Full detail: `docs/season_eve_2026_dryrun.md` §5.

- **`is_home` dropped from all three models' features** — it is a constant 0.5
  in real nflverse data (no home/away column), collinear with the intercept,
  and the unregularised GLM gave it an arbitrary coefficient (+2.0 on
  passing_yards) that swung `future_row` means 3-7×. Historical-path
  predictions are **numerically unchanged** (constant absorbed by the refit
  intercept — `model_backtest` holdout + `preseason_baseline_2026.md` reproduce
  exactly).
- **Cold-start shrinkage redesigned** (`future_row`, no same-season priors):
  blend the GLM point estimate with the player's trailing average, weighting
  the GLM by the prior-season game count (capped 10); clamp to `[0.4, 1.8] ×
  trailing`; no history ⇒ league prior. Kills the 600-1000 yд projections —
  Week-1 slate proj / recent-form ratio median 0.93, max 1.88, 5% outside
  [0.5, 2.0].
- **`recalibrate_spread()` + `residual_cv()`** in `models/dist_family.py`:
  rescale each stat's distribution to a robust residual CV so `P(over)` is
  informative rather than stuck at ~0.5. **`future_row`-gated** — historical /
  replay / backtest path untouched.
- **`use_future_row` False -> True.** `data/nflverse_loader.py` now skips a
  404 (unpublished) weekly year instead of crashing;
  `evaluation_service.scoring_weekly()` widens the fit + history window to
  every complete season through the scored one (a 2026 request was training
  only through ~2023). `POST /api/props/evaluate` for a Week-1 2026 prop
  returns a realistic mean + informative probability.
- **Known residual gap:** the 2018-2024-locked GLMs over-project 2025/2026
  yardage ~+24yd (QB) / ~+4yd (WR) because 2025 was a lower-output environment;
  the cold-start blend dampens but does not remove it. Full probability
  calibration still needs real market lines or a held-out-actuals calibration
  layer — not an eve-of-season change.
- `tests/test_predict_with_future_row.py` fixture widened to 2 seasons.

**Verification:** `uv run pytest -q` -> 351 passed; `model_backtest` holdout +
`preseason_baseline_2026.md` byte-identical to v0.9-m3 (historical path
unchanged); 2026 Week-1 realism + live `/api/props/evaluate` spot-checked.

---

## v0.9-m3 - 2026-09-08

**Season-eve activation: data brought current for 2026; training + paper-execution pipelines exercised end to end on refreshed 2025 data.**

Full detail: `docs/season_eve_2026_dryrun.md`.

- **Data current for 2026:** `ALL_YEARS` -> ..2026; schedule / injury / roster cache windows extended to 2026. Caches refreshed (weekly 217,490 rows; schedules incl. 2026's 272 games; rosters/injuries through 2026). `TRAIN_YEARS` stays 2015-2024 / `HOLDOUT_YEARS` [2025] — the two must stay disjoint (out-of-sample test set for `model_backtest` / `replay_pipeline`); production fits pass explicit `years=`. **nflverse has no 2026 player data yet (lands after Week 1) and no preseason box scores ever** — "train on preseason" is not possible from these sources; 2025 is the freshest complete season.
- **`docs/training/synthetic_props_training.csv` regenerated:** 144,562 rows (2019-2025), all eligible; 2025 fully resolved (21,108 rows, 0 null outcomes).
- **`scripts/capture_preseason_baseline.py` wired for real** (was a stub returning `[]`): fits the locked GLMs, scores per (position, stat) on 2025 -> `docs/preseason_baseline_2026.md`. Finding: **`rb/carries` is badly miscalibrated** (log_loss 2.35 / brier 0.46, worse than uninformed) despite fine point accuracy (MAE 4.2) — a tail/distribution problem for `use_calibration` once real lines exist. Other stats 0.49-0.80 log_loss.
- **Training accuracy re-run** (`eval/model_backtest.py`, locked config, disjoint 2025 holdout): **every stat's MAE + RMSE improved vs the April baseline** on both walk-forward and holdout (data volume + upstream corrections, not leakage). QB `passing_yards` keeps a ~+25 yd/game positive bias (pre-existing).
- **Paper-trade replay 2025** -> `docs/paper_trade_summary_2025.md`: 18,801 singles, ROI +7.6%, win rate 56.4% vs synthetic surrogate lines (model-vs-trend, not real edge).
- **`scripts/dry_run_execution.py`** (new): first end-to-end exercise of `ExecutionService -> mapper -> ExposureRiskEngine -> RealisticPaperAdapter -> ledger`. 1,500 replay picks -> 1,500 filled, `docs/audit/` persistence verified.
- **`scripts/dry_run_week1_2026.py`** (new): real Week-1 slate -> price -> paper-submit. Plumbing works (847/847 filled). **BLOCKER surfaced:** the `future_row` forward-scoring path is not season-ready — Week-1 predictions collapse to the league prior (`use_future_row=False`), and the decomposed passing-yards path over-projects to 600-1000+ yd when that collapse is removed. `use_future_row` stays `False`; nothing shipping for Week 1 depends on it.
- **Fixes:** `generate_synthetic_props.py` + `capture_preseason_baseline.py` were un-runnable (missing repo-root `sys.path`); `RealisticPaperAdapter` no longer logs the misleading "fake paper adapter active" line; `.gitignore` for `docs/audit/` and dry-run scratch.
- **Deferred:** full 144-config walk-forward grid re-validation (locked config is human-reviewed; ~hours, low value); calibration (still gated on real Kalshi quotes); live weather forecast for 2026 games.

**Verification:** `uv run pytest -q` green.

---

## v0.9-m2 - 2026-06-10

**Modernization roadmap accepted + pre-work shipped: breakpoint Layer B gate, PR template, Kalshi NFL series discovery, preseason baseline scaffold.**

Per `docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md` (cross-phase design for P2-P7). Per-phase implementation specs will be authored at the triggers in `memory/roadmap_orchestration.md`.

- **`docs/breakpoints/`** (new): `_template.md` and `README.md` define Layer B adversarial evaluation per roadmap §5 P3. Every phase ships a `p<N>_evaluation.md` covering boundary probes, outlier injection, exception paths, and hypothetical failure modes.
- **`scripts/check_breakpoint_doc.py` + `tests/test_breakpoint_doc_gate.py`** (new): merge gate — a PR touching `api/trading/`, `eval/`, or `models/` must reference `docs/breakpoints/p<N>_evaluation.md` (in diff or PR body). Roadmap R11 mitigation.
- **`.github/PULL_REQUEST_TEMPLATE.md`** (new): PR checklist with Layer A test plan, Layer B link, roadmap risk references.
- **`scripts/discover_kalshi_nfl_series.py` + tests** (new): paginated enumeration of Kalshi series via existing `KalshiClient` signing, filtered to `KXNFL*`, dumps `cache/kalshi_nfl_series.json`. Roadmap R1 mitigation — retires the "do NFL series exist?" question well ahead of P4.
- **`scripts/capture_preseason_baseline.py` + tests** (new): uncalibrated Brier + log_loss per (position, stat) scaffold → `docs/preseason_baseline_2026.md`. Metric and formatting helpers tested; runtime model integration is intentionally deferred to first real run. Roadmap pre-gate item 5.
- **`memory/roadmap_orchestration.md`** (new): operator runbook — when to fire each per-phase brainstorm, with prompt templates; cross-phase invariants (model > GUI, LLM downgrade-only, walk-forward only, Layer B gate).

**Verification:** `uv run pytest -q` green (new tests: 4 gate + 5 discovery + 8 baseline = 17 added).

---

## v0.8c - 2026-04-29

**Phase H complete: per-stat configuration locked into model defaults; ModelingNotes documents the rationale; calibration deferred to v0.9.**

- **Per-position fit() defaults locked from cross-season Phase H walk-forward evidence:**
  - `models/qb.py`: `dist_family="decomposed"`, `k=2`, `l1_alpha=0.0`, `use_weather=False` — passing_yards uses Monte Carlo composition; completions/passing_tds/interceptions automatically route through count_aware NegBin/Poisson.
  - `models/rb.py`: `dist_family="count_aware"`, `k=2`, `l1_alpha=0.0`, `use_weather=False` — rushing_yards uses count_aware quantile path; carries/rushing_tds use count_aware NegBin/Poisson.
  - `models/wr_te.py`: `dist_family="decomposed"`, `k=2`, `l1_alpha=0.0`, `use_weather=False` — receptions uses targets×catch_rate composition; receiving_yards/receiving_tds use count_aware paths.
- **Universal findings (all 10 stats):** `k=2` is monotonically best (pooled log_loss strictly increases with k); weather effect is in the noise (-0.0001 to +0.0076 log_loss, ~2,227 outdoor games is too thin to fit weather coefficients reliably); L1 effects are in the noise (0.0001-0.005 per stat, no consistent direction).
- **dist_family architectural fact:** `decomposed` is functionally identical to `count_aware` for 7 of 10 stats — decomposition is only implemented for `passing_yards`, `rushing_yards`, `receptions`. The auto-generated `per_stat_majority_config.csv` reports `dist_family=decomposed` for some arbitrary-tiebreak cases; lock chose `count_aware` (the actual underlying model) for honesty.
- **Two empirical concessions for architectural cleanliness:** `rb/rushing_tds` and `wr_te/receiving_tds` were 0.0001-0.0002 better with `legacy`, but lock chose `count_aware` so all count stats use one family.
- **`use_calibration: bool = False`** added to `api/settings.py`. Mean `max_reliability_dev` across locked configs was 0.44-0.48, but evaluated against synthetic surrogate odds rather than real captured market lines. Calibrator deferred until v0.9 ships real Kalshi quote capture.
- **Three grid axes never varied** (`use_opponent_epa`, `use_rest_days`, `use_home_away`) — shipped 144-config grid only varied 4 axes. Locked False with note in ModelingNotes for v0.9 H2.1 mini-grid.
- **2019 had 288 QB fit_errors** (only 2018 as training data is too thin for regularized count_aware/decomposed); 2019 1-vote QB winners discarded as artifacts.
- `tests/test_l1_path.py::test_k_default_is_eight` renamed to `test_k_default_is_two` reflecting the new H5 locked default.
- `docs/ModelingNotes.md` extended with full Phase H5 section: locked defaults table, universal findings, dist_family architectural facts, tight-pack stats analysis, season anomalies, calibration deferral rationale, deferred-to-v0.9 list.
- Per-season Qwen 1.7B narration (Phase H3): `scripts/narrate_season.py` now uses `/v1/chat/completions` with `/no_think` system prompt and Bearer auth (the 1.7B model burned all tokens in thinking mode otherwise); `_FREEFORM_MAX_TOKENS` raised 80→120; `--api-key` flag added; all 7 season summaries written with real Qwen-generated qualitative notes to `docs/training/season_<YYYY>_summary.md`.

**Verification:** `uv run pytest -q` → **315 passed, 5 deselected** in 70 seconds.

---

## v0.8c-h2-complete - 2026-04-29

**Phase H2 complete — `scripts/train_loop.py` + all seven walk-forward season result CSVs.**

- **`scripts/train_loop.py`** shipped: deterministic ablation grid, row-level resume/checkpoints, evaluation vs `docs/training/synthetic_props_training.csv` per `docs/superpowers/specs/2026-04-28-h2-train-loop-design.md`.
- **`tests/test_train_loop.py`** + **`tests/test_l1_path.py`** cover grid/hash metrics and L1 paths.
- **`docs/training/season_<YYYY>_results.csv`** for holdout seasons **2019–2025** (7 files); each complete season file has **1,440 rows** (**144 configs × 10 stats**), one unique `(config_hash, position, stat)` per row.
- **Next (H4 aggregation):** `uv run python scripts/synthesize_training.py` (optional `--results-dir docs/training/`; use `--allow-partial` only if some season files are missing). Produces `per_stat_majority_config.csv`, `cross_season_summary.md`, and `cross_season_reliability.png`, then optional Qwen narration for rollup notes when the local LLM URL is up.

**Verification:** `uv run pytest -q tests/test_train_loop.py tests/test_l1_path.py` (and full suite as usual before merge).

---

## v0.8c-h2-holdouts-2019-2020 - 2026-04-29

**Phase H2 walk-forward output checkpoint: 2019 and 2020 complete.**

- Completed `docs/training/season_2019_results.csv` and `docs/training/season_2020_results.csv`.
- Each completed holdout file has **1,440 rows**: **144 configs × 10 stats**, with one unique `(config_hash, position, stat)` key per row and no duplicate keys.
- *(Checkpoint only — superseded by **v0.8c-h2-complete**.)* Previously: remaining holdouts **2021-2025**; finish `train_loop` before `synthesize_training.py`.

---

## v0.8c-h4-reporting-correction - 2026-04-29

**Phase H reporting logic correction: 2025 is consumed by H4 voting.**

- Supersedes the six-holdout note in `v0.8c-h2-session-c`: H4 majority-vote reporting now treats **2019-2025** as the official seven-season walk-forward span.
- **2025 is no longer pristine `final_eval`** once `scripts/train_loop.py` produces `season_2025_results.csv`; any true final evaluation after H5 must use a later season or explicitly documented out-of-band protocol.
- H5 production lock remains **per `(position, stat)`** from `per_stat_majority_config.csv`; the global mean-variance config is a benchmark only.

---

## v0.8c-h2-session-c - 2026-04-28

**Phase H Session C — H2 Opus brainstorm (pre-implementation locks) + synthetic training backfill.**

- **Session sequencing:** Opens after Session B close (**5528363**). Deliverable targets `scripts/train_loop.py`: walk-forward discipline, **`docs/training/synthetic_props_training.csv` coverage**, and a frozen **results CSV schema** grounded in existing eval paths (`prob_over(line)` vs `outcome_over` log-loss aligns with Phase H definition of done). Checkpoint format and **parallelism across the 1152-config grid** remain to be finalized alongside the first implementation pass (no separate lock documented in-session).
- **Synthetic props backfill (prereq for H2/H4 Pareto across seasons):** Regenerated labeled training CSV with `uv run python scripts/generate_synthetic_props.py --seasons 2019,2020,2021,2022,2023,2024,2025 --emit-training-dataset --training-out-file docs/training/synthetic_props_training.csv`. **144,414 rows** across **2019-2025** (deterministic from nflverse weekly; no API calls). Older **v0.8c-data** snapshot (~41k rows, 2024-2025 only) is superseded for Phase H tooling. Row counts vs prior snapshots can drift when upstream nflverse/cache history grows (2024 regenerated slightly larger vs the pre-backfill artifact).
- **Walk-forward discipline (locked):** **Six** expanding-window steps — train cumulative **2018..(holdout−1)**, holdout season **holdout ∈ {2019…2024}** one step per row in the table below. **2025** labeled rows stay in the CSV for **H4.5/H5 `final_eval`** only; they are **not** a seventh ablation holdout (that would consume the reserved final-eval window). Alternative considered: single holdout year only — rejected because H4 cross-season Pareto selection requires multi-year variance.

  | Step | Train years | Holdout |
  |------|-------------|---------|
  | 1 | 2018 | 2019 |
  | 2 | 2018–2019 | 2020 |
  | 3 | 2018–2020 | 2021 |
  | 4 | 2018–2021 | 2022 |
  | 5 | 2018–2022 | 2023 |
  | 6 | 2018–2023 | 2024 |

- **Holdout evaluation source (confirmed):** For each `(holdout_season, config, position, stat)` — fit models on training years with that config’s flags; for each synthetic row matching `season == holdout_season` and the stat/position, **`log_loss` from `prob_over(line)` vs `outcome_over`** (plus sanity metrics aligning with `model_backtest`-style reporting).
- **`docs/training/season_<YYYY>_results.csv` schema (frozen, `YYYY` = holdout season):** One row per `(config_hash, position, stat)` (~**11,520** rows per file: 1152 configs × 10 stats).

  | Group | Columns |
  |-------|---------|
  | IDs | `config_hash`, `holdout_season`, `position` (qb \| rb \| wr_te), `stat` |
  | Config (flat filters) | `use_weather`, `use_opponent_epa`, `use_rest_days`, `use_home_away`, `dist_family`, `k`, `l1_alpha` |
  | Sizes | `n_train`, `n_holdout` |
  | Selection metric | `log_loss` (primary vs synthetic labels) |
  | Calibration / point sanity | `brier`, `mae`, `rmse`, `bias` |
  | GLM diagnostics | `aic` (nullable for `_ConstantResult` / non-GLM paths), `max_reliability_dev` (max deviation from diagonal, **10 equal-width bins** on predicted probability [0,1]) |
  | Fit metadata | `fit_seconds`, `convergence_flag` (`ok` \| `constant_fallback` \| `fit_error`) |

  Notes: **`config_hash`** — stable digest of the seven knobs for resume/dedup. **Reliability:** 10 equal-width bins. **Decomposed / Monte Carlo stats:** `prob_over` from sampled tails; **`aic`** may be null where no single fitted GLM applies.

**Verification:** `uv run pytest -q` → **278** passed, **5** deselected (post-backfill regression).

---

## v0.8c-h2.5 - 2026-04-28

**Phase H Session B close: residual-based uncertainty (`H2.5`).**

- H2.5: Replaced hand-scaled std formula (`prior_std * shrunk_mean / max(prior_mean, _MIN_MEAN)`) in `_legacy_distribution()` across all three position models with empirical residual std computed at `fit()` time (`np.std(y_fit - y_pred_train)`). Fixes the single biggest tail-pricing risk identified in the Phase H spec.
- H2.5: Added `self._residual_stds: dict[str, float]` to `QBModel`, `RBModel`, and `WRTEModel`. Populated after each GLM fit on the legacy path; count-aware stats already carry model-implied dispersion; decomposed path derives uncertainty from Monte Carlo composition.
- H2.5: `_legacy_distribution()` emits `DeprecationWarning("No empirical residual std cached...")` when called on an unfitted model and falls back to the old formula, preserving the unfitted-predict contract for existing callers.
- H2.5: Added `tests/test_residual_uncertainty.py` — 11 tests covering populated-after-fit, positive-valued stds, no-warning path after fit, DeprecationWarning path without fit (QB/RB/WR-TE), and residual-std ≤ prior-std cross-model consistency check.

**Verification:** `uv run pytest -q tests/test_residual_uncertainty.py` -> 11 passed; `uv run pytest -q` -> 278 passed, 5 deselected.

---

## v0.8c-h1.5 - 2026-04-28

**Phase H Session B start: stat-specific distribution architecture (`H1.5`).**

- H1.5: Extended `models/base.py::StatDistribution` so the shared prediction contract can represent classic GLM tails, count-aware families, quantile-driven tails, and empirical sample distributions while preserving `prob_over(...)` for pricing and replay callers.
- H1.5: Added `models/dist_family.py` to centralize count-family fitting, quantile-regression helpers, and decomposition composition logic for Monte Carlo-based distributions.
- H1.5: `models/qb.py` now accepts `dist_family` in `fit(...)`; count stats (`passing_tds`, `interceptions`, `completions`) use Poisson/negative-binomial logic on non-legacy paths, `passing_yards` gets quantile companions, and `decomposed` builds a sampled passing-yards distribution from attempts x yards-per-attempt.
- H1.5: `models/rb.py` now accepts `dist_family` in `fit(...)`; count stats (`carries`, `rushing_tds`) use count-aware families, `rushing_yards` gets quantile companions, and `decomposed` builds a sampled rushing-yards distribution from carries x yards-per-carry.
- H1.5: `models/wr_te.py` now accepts `dist_family` in `fit(...)`; count stats (`receptions`, `receiving_tds`) use count-aware families, `receiving_yards` gets quantile companions, and `decomposed` builds a sampled receptions distribution from targets x catch rate.
- H1.5: Updated `eval/fantasy_points.py` to sample directly from `StatDistribution`, so fantasy simulations stay compatible with the new empirical and quantile-backed distributions.
- H1.5: Added `tests/test_dist_families.py` covering quantile lookup behavior, count-aware zero-mass handling, and a hand-check for decomposed receptions.

**Verification:** `uv run pytest -q tests/test_dist_families.py` -> 3 passed; `uv run pytest -q tests/test_models.py tests/test_fantasy_points.py tests/test_predict_with_future_row.py` -> 19 passed; `uv run pytest -q tests/test_model_weather.py` -> 15 passed; `uv run pytest -q tests/test_prop_pricer.py` -> 19 passed.

---

## v0.8c-h1-fixes - 2026-04-28

**Phase H follow-up fixes: weather-aware loading, regularized AIC preservation, and tighter H1 verification.**

- H1: When `use_weather=True`, all three position models now load `load_weekly_with_weather(...)` instead of silently training on the plain weekly frame with zero-filled weather columns.
- H1: Added `models/glm_utils.py` to centralize GLM fitting. The L1 path now uses `statsmodels.GLM.fit_regularized(..., refit=True)` so regularized fits keep finite coefficients and real `.aic` values for later H3/H4 reporting.
- H1: Expanded `tests/test_model_weather.py` with coverage for weather-loader selection, regularized-fit AIC availability, bounded weather on/off AIC drift, and direct statsmodels-vs-sklearn Gamma parity to `1e-2`.
- Data: `scripts/prefetch_training_cache.py` — one-shot nflverse parquet warmup (`weekly` 2014–2025, `schedules` 2018–2025, `injuries` 2015–2025, then `load_weekly_with_weather` for 2015–2025); optional `--force` to bypass 24h freshness.
- Data: `scripts/backfill_weather.py` — Open-Meteo free-tier pacing (`--min-interval`, default 1.05s between outdoor calls), HTTP 429 retries with `Retry-After` + backoff, 120s request timeout, line-buffered stderr logging, and schedule alias `LA`→`LAR` for Rams home games; `process_games(..., min_interval_sec=...)`.
- Data: `tests/test_weather_backfill.py` — outdoor pacing param rename, 429 retry/exhausted coverage via mocked `requests.get`.

**Verification:** `uv run pytest -q tests/test_model_weather.py tests/test_calibration_disjoint.py` -> 23 passed; `uv run pytest -q tests/test_weather_backfill.py` -> 25 passed.

---

## v0.8c-h1-h4.5 - 2026-04-28

**Phase H Session A: statsmodels GLM migration (H1) + four-window calibration discipline (H4.5).**

- H1: Migrated all three position models (`models/qb.py`, `models/rb.py`, `models/wr_te.py`) from sklearn `GammaRegressor`/`PoissonRegressor`/`TweedieRegressor` to `statsmodels.GLM` with identical family/link mappings (Gamma-Log, Poisson, Tweedie-1.5-Log). Models now expose `.aic` on fitted results, enabling H3 narration slots.
- H1: Added `l1_alpha: float = 0.0` parameter to all three `fit()` methods. When nonzero, uses `glm.fit_regularized(alpha=l1_alpha, L1_wt=1.0)`. Default off — plain GLM, no regularization until H2 ablation grid validates the path.
- H1: Added flag-guarded weather features (`use_weather: bool = False`) to `_build_features()` on all three models. QB adds `wind_mph`, `precip_in`, `temp_f_minus_60`, `wind_x_pass_attempt_rate`; RB/WR-TE add the first three. Indoor games (`indoor=True`) get zero for all weather features. Default off until H2 ablation validates inclusion.
- H1: Added `_ConstantResult` fallback in all three models for degenerate/sparse training sets (replaces NaN-crashing GLM initialization on minimal data with graceful constant-mean prediction).
- H1: Added `statsmodels>=0.14.0` (+ `patsy`) to `pyproject.toml`.
- H1: `tests/test_model_weather.py` — 11 tests covering weather feature presence/absence by flag, indoor masking, QB-only interaction term, prediction range sanity, and AIC accessibility.
- H4.5: New `eval/calibration_fit.py` — `assert_four_window_disjoint()` enforces model_train ⊥ calibrator_fit ⊥ policy_tune ⊥ final_eval across all six pairwise combinations; `build_training_windows()` returns the default Phase H split (model_train: 2018-2021, calibrator_fit: 2022, policy_tune: 2023-2024, final_eval: 2025 - reserved).
- H4.5: `tests/test_calibration_disjoint.py` — 8 tests covering all pairwise overlap cases, error message contents, empty window handling, and default window disjointness.

**Verification:** 260 Python tests passing, 5 deselected.

---

## v0.9a-training - 2026-04-27

**Training hooks for synthetic-surrogate odds and future-row ablation.**

- Added `eval/training_dataset.py` to load `docs/training/synthetic_props_training.csv`, filter `eligible_for_training=True`, validate `market_source=synthetic_surrogate_v1`, and centralize odds/provenance/outcome feature exclusions
- Wired `use_future_row` as an explicit replay/calibration/evaluation/fantasy flag path while keeping the default off until Phase H evidence supports flipping it
- Added training dataset tests that validate no-vig market columns against the pricing utility and keep odds/outcome columns out of model features

**Verification:** included in full suite: 240 Python tests passing, 5 deselected.

---

## v0.8g-ui - 2026-04-27

**Weather, injury, and decision drawer surface.**

- Extended pick schemas and frontend types with optional weather, injury, no-vig, EV, recommendation, confidence, and driver fields so old replay artifacts still load
- Enriched replay picks with archive weather when available and cached injury statuses when present; missing feeds continue to render honest fallback states
- Updated `WeatherBadge`, `InjuryPill`, and `PlayerCard` to use real payload fields, and added a Radix decision drawer with model/market probabilities, EV, recommendation, confidence, and driver slots

**Verification:** `npm.cmd test -- --run` passed (17 tests); `npm.cmd run build` passed.

---

## v0.8f-execution - 2026-04-27

**Side-aware paper execution and realistic fills.**

- Added side/action fields to order events, side-aware portfolio keys, realized close P&L, mark-to-market, and settlement transitions
- Added `RealisticPaperAdapter` with spread, next-tick executable price, non-fill probability, and partial fills while keeping `FakePaperAdapter` for unit tests
- Added `ExposureRiskEngine` with side-aware worst-case loss, market-lock buffer, per-side inventory caps, daily loss cap, and static-risk fallback wiring

**Verification:** full trading tests included in the 240-test Python suite.

---

## v0.8e-pricing - 2026-04-27

**No-vig pricing, decision object, and EV selection.**

- Added `eval/no_vig.py::remove_vig_two_sided()` with multiplicative/additive methods and an explicit Shin `NotImplementedError`
- Added frozen `PropDecision` pricing output while preserving the existing dict-shaped two-sided pricing wrapper
- Updated paper-pick selection to rank by expected value, emit no-vig market probabilities and EV fields, and mark below-threshold rows as `no_bet`
- Added settings for no-vig, EV threshold, player/game caps, and correlation-penalty gating

**Verification:** no-vig, decision, replay, and synthetic odds tests included in the 240-test Python suite.

---

## v0.8d-preflight - 2026-04-27

**Preflight safety fixes before pricing/execution/training work.**

- `load_weekly_with_weather()` now always returns stable weather columns, even when `cache/weather_archive.parquet` is missing
- Unmatched weather joins now default `indoor=True` with null numeric weather fields, matching the Phase G contract
- Added train/holdout overlap guards in calibration and replay before model fitting
- Fixed execution SSE cursor advancement so streams do not skip events
- Added `weather_archive_available` replay metadata for H weather ablations

**Verification:** weather, calibration, replay, and SSE-adjacent coverage included in the 240-test Python suite.

---

## v0.8c-data - 2026-04-27

**Training-grade synthetic odds dataset for Phase H/J/K prep.**

- Added an additive training mode to `scripts/generate_synthetic_props.py` via `--emit-training-dataset` and `--training-out-file`, while keeping the default `docs/synthetic_replay_props.csv` replay seed behavior unchanged
- Generated `docs/training/synthetic_props_training.csv` with 41,508 rows, varied leakage-safe surrogate odds, no-vig market probabilities, actual outcomes, provenance fields, and line/odds outlier flags
- Synthetic training odds now use only pre-game player history, recency-weighted empirical hit rates, shrinkage toward 0.50, stat-specific vig, American-odds rounding, and explicit `market_source=synthetic_surrogate_v1`
- Added tests covering legacy output stability, training schema compatibility, odds variation, no-vig probability sums, determinism, target-game leakage protection, outlier flag behavior, replay compatibility, `/api/slate` stability, and Phase H feature-exclusion guards

**Verification:** 220 Python tests passing, 5 deselected.

---

## v0.8b-fgfp - 2026-04-27

**Future-Game Feature Pipeline (Phase G.5).**

- G.5-1: `data/upcoming.py::build_upcoming_row(player_id, season, week, *, position, opponent_team, recent_team, is_home=None, weather=None, weekly=None)` — builds a feature dict for an unplayed game by appending a stat-zero placeholder row to the historical weekly frame and re-running the position's `_build_features`. Reuses training feature semantics exactly; no parallel rolling/lagging logic. Returns dict whose keys are a strict superset of the model's `_feature_cols`.
- G.5-2: `models/{qb,rb,wr_te}.py::predict()` gained `future_row: dict | None = None` kwarg. When supplied, the feature vector is built from the dict via `np.array([[row.get(col, 0.0) for col in self._feature_cols]])`. Legacy `opp_team` arg is now optional and emits `DeprecationWarning` when used without `future_row` (will be removed after Phase H).
- G.5-3: `tests/test_upcoming.py` — 8 tests covering opp-context shift, player-rolling stability, weather pass-through, is_home override, position dispatch (QB/RB/WR-TE), unsupported-position guard
- G.5-3: `tests/test_predict_with_future_row.py` — 5 tests covering BUF vs MIA distribution divergence, same-opponent stability, deprecation warning on legacy path, no-warning on cold model, future_row overrides opp_team
- `api/settings.py::use_future_row: bool = False` (env: `NFL_APP_USE_FUTURE_ROW`) — flag to gate replay/scoring services on the future-row path. Default off until Phase H ablation locks the config.
- `docs/ModelingNotes.md` — new file documenting what landed, what was deferred to Phase H (PBP-EPA in `data/team_context.py`, snap-share, injury swap), and the expected delta vs pre-FGFP replay output.

**Verification:** 212 Python tests passing, 5 deselected (slow). +13 new G.5 tests over v0.8b baseline.

---

## v0.8b - 2026-04-25

**Historical weather backfill + loader integration (Phase G2+G3).**

- G2: `scripts/backfill_weather.py` — Open-Meteo Archive backfill for NFL games 2018–2025; indoor skip (fixed dome + retractable); unit conversions (°C→°F, km/h→mph, mm→in); 3× exponential backoff on 5xx; 429/403 clean stop; idempotent; writes `cache/weather_archive.parquet`
- G2: `tests/test_weather_backfill.py` — 24 tests covering indoor skip, outdoor unit conversion, idempotency, 5xx retry, 429/403 stop
- G3: `data/weather.py` — `load_archive(seasons)` reads cache parquet (empty-safe, stable schema); `load_forecast(game_id)` stubbed, gated on `use_live_forecast` flag
- G3: `data/nflverse_loader.py` — `load_weekly_with_weather(years)` left-joins player stats to weather archive by `game_id`; unmatched games get `indoor=True` and null numeric weather columns
- G3: `api/settings.py` — `use_live_forecast: bool = False` added
- G3: `tests/test_weather_loader.py` — 5 tests covering archive miss, season filter, forecast stub (flag on + off), join correctness, empty-archive schema stability

**Verification:** 201 Python tests passing, 5 deselected (slow/integration marks).

---

## v0.8a-scaffold - 2026-04-24

**Kalshi scaffold: module shape, secret vault, RSA-PSS signing, KalshiMapper stub, venue selector UI.**

- F1: `api/trading/kalshi/{__init__,client,adapter,ws}.py` — Kalshi module fully shaped; all network methods raise `NotImplementedError("Kalshi scaffold — activate in-season")`; class wiring, type signatures, and `client_order_id` handling in place
- F1: `api/trading/kalshi/signing.py` — real RSA-PSS signing (`sign_request`); tested against a generated test keypair without network access
- F2: `api/trading/secrets.py` — `keyring` wrapper: `store/load/delete` under `nfl-prop-workstation` service; venue-namespaced keys
- F2: `api/routes/secrets.py` — `POST /api/secrets/kalshi` stores access key + PEM; gated by startup-printed confirmation token; registered in server.py
- F2: `pyproject.toml` — added `cryptography>=42`, `keyring>=25`
- F3: `tests/trading/test_kalshi_signing.py` — 4 tests: base64 length, PSS round-trip verify, payload isolation, bytes PEM
- F2: `tests/trading/test_secrets.py` — 5 tests: round-trip, missing→None, delete, delete-noop, venue isolation
- F4: `api/trading/mapper.py` — `KalshiMapper` added; `map_signal` returns `None` and logs `mapping_skipped` audit event
- F5: `desktop/src/routes/execution-page.tsx` — venue selector dropdown in banner: "Paper" (active) / "Kalshi (Demo) — Coming preseason" (disabled)
- F6: `docs/TradingOps.md` — paper vs demo vs live, secret-vault usage, kill-switch semantics, Kalshi activation checklist, compliance disclaimer

**Verification:** 47 Python trading tests passing; 16 frontend tests passing; `npm run build` clean.

---

## v0.7b-scaffold - 2026-04-24

**Paper trading surface: fake adapter, execution service, API routes, execution UI page.**

- E1: `api/trading/paper_adapter.py` - `FakePaperAdapter` (all adapter protocols); immediate fill at limit price; rejects invalid price/size; `KillSwitch` trip/reset; logs warning on first use
- E2: `api/services/execution_service.py` - `ExecutionService` orchestrates pick→mapper→risk→router→ledger; in-memory event log; `submit_picks`, `cancel`, `get_portfolio`, `get_events`, `trip_kill_switch`
- E2: `api/routes/execution.py` - 6 routes: `POST /paper/submit`, `POST /paper/cancel`, `POST /kill`, `GET /portfolio`, `GET /events`, `GET /events/stream` (SSE tail)
- E2: `api/server.py` - execution service wired at startup; `StaticRiskEngine` uses `NFL_APP_RISK_*` env settings
- E3: `desktop/src/routes/execution-page.tsx` - 3-panel layout: pick queue + per-pick Submit, orders + Cancel, portfolio P&L + live SSE event tail
- E3: `desktop/src/App.tsx` + `router.tsx` - "Execution (Paper)" nav link and `/execution` route
- E3: `desktop/src/lib/api.ts` + `types.ts` - `submitPicks`, `cancelIntent`, `killSwitch`, `getPortfolio`, `getExecutionEvents`, `streamExecutionEvents`; `IntentStatus`, `Portfolio`, `ExecutionEvent` types
- E4: Kill switch big red button in banner, wired to `POST /kill`; flips all open intents to canceled; disables after trip
- E5: `desktop/src/routes/__tests__/execution-page.test.tsx` - 5 tests: banner visible, pick renders, submit shows intent, cancel flips status, kill switch disables

**Verification:** 38 Python trading tests passing; 16 frontend tests passing (4 files); `npm run build` clean.

---

## v0.7a - 2026-04-24

**Trading domain types, audit log, adapter protocols, risk engine, ledger, pricing.**

- D1: `api/trading/types.py` - frozen dataclasses: Signal, MarketRef, ExecutionIntent (with `edge` field), RiskDecision, OrderEvent, Position, PortfolioState
- D2: `api/trading/adapters.py` - Protocol classes: MarketDiscoveryAdapter, SignalMapper, RiskEngine, OrderRouter, MarketDataStream, OrderStatusTracker, PortfolioLedger, KillSwitch
- D2: `api/trading/audit.py` - `log_event()` appending JSONL for every order-lifecycle event
- D3: `api/trading/risk.py` - `StaticRiskEngine` with 5 caps (max notional/order, max open notional/market, daily loss cap, min edge, reject cooldown); trips kill-switch after N rejects in M seconds; configured via `NFL_APP_RISK_*` env prefix in `api/settings.py`
- D4: `api/trading/ledger.py` - `InMemoryPortfolioLedger` applies fills/partials to Position map; weighted avg price; persists snapshot to `docs/audit/portfolio-<session>.json`
- D5: `api/trading/pricing.py` - `american_to_prob()` and `prob_to_clob_price()` utilities; `api/trading/mapper.py` - `PickToIntentMapper` (Signal + MarketRef → ExecutionIntent)

**Verification:** 30 new trading tests all passing (`tests/trading/`); existing suite unaffected.

---

## v0.6c - 2026-04-24

**Telemetry + frontend test baseline.**

- C1: FastAPI exception handlers (HTTP, validation, generic) emit `{success, data, error:{code,message,request_id}}` envelope; frontend `request()` unwraps error envelope for richer messages; fixed silent error swallow in `streamAnalyst` catch block
- C2: `app-store.ts` expanded with theme, minEdgeDefault, defaultStatFilter, simpleMode; zustand `persist` middleware with `localStorage` key `nfl-prop-workstation:prefs`; apiBaseUrl excluded from persistence
- C3: OpenTelemetry wired - `api/telemetry.py` with custom `_JsonlSpanExporter` writing to `docs/telemetry/spans-<date>.jsonl`; `FastAPIInstrumentor` auto-traces all routes; `opentelemetry-api/sdk/instrumentation-fastapi` added to deps
- C4: `vitest`, `@testing-library/react/jest-dom/user-event`, `jsdom` installed; `vitest.config.ts` + `src/test/setup.ts`; 3 test files (dashboard, parlay-builder, analyst-panel) — 11 tests, all passing; `"test"` script in package.json

**Verification:** `102 passed, 4 deselected` Python; `cd desktop && npm test` → 11 passed; `npm run build` clean.

---

## v0.6b - 2026-04-24

**Beginner UX + honest placeholders.**

- Removed "step 5 v0.5a" and "Step 4 replay artifacts" dev-facing strings from dashboard; replaced with `{slate.season_label}` label and plain-English copy
- Filters card upgraded from read-only display to real controls: position multi-select, min-edge range slider, stat multi-select; state local, filtering client-side against React Query cache
- `WeatherBadge`: null renders "No current feed" instead of "Weather N/A"
- `InjuryPill`: null renders "Status unknown" instead of "Active"
- Analyst panel: 3 starter chips appear when input is empty ("Explain this pick in plain English", etc.); player-detail now passes `stat` and `line` context from top pick
- New `GlossaryTooltip` component (CVA, ~45 lines): hover definition tooltips on Singles ROI, Profit Units, Parlay EV KPI labels; 8-term dictionary in same file
- B6: `@axe-core/playwright` installed; `playwright.config.ts` + `desktop/tests/a11y.spec.ts` added asserting zero `wcag22aa` violations on all 3 routes with mocked API

**Verification:** `npm run build` clean; Python suite unchanged.

---

## v0.6a - 2026-04-24

**Workstation leaks fixed.**

- Replaced Vite-template `<title>desktop</title>` with `NFL Prop Workstation`; rewrote `desktop/README.md` with dev/build/route docs
- Tightened Tauri CSP from `null` to a real policy (loopback `connect-src`, no `unsafe-inline` on scripts, Tailwind `unsafe-inline` on styles)
- Scoped CORS origins from wildcard to `["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"]`
- Aligned analyst SSE contract: backend emits `tool_call` events for llama.cpp tool-call deltas; frontend surfaces server-side `error` events by throwing in `streamAnalyst`; new `tests/test_analyst_stream.py`
- Wired `@tanstack/react-query` (was installed, unused): `QueryClientProvider` in `main.tsx`; all three route pages converted from `useLoaderData` to `useQuery`; deleted `dashboard-loader.ts` and `player-detail-loader.ts`; removed `loader:` and `hydrateFallbackElement:` from router

**Verification:** `101 passed, 4 deselected` Python suite + `test_analyst_stream` passing; `npm run build` clean (0 TS errors).

---

## v0.5.1 - 2026-04-23

**Step 5 fantasy projection layer and desktop sidecar startup fix.**

- Added a Full PPR fantasy predictor that reuses the existing prop/stat model distributions, emits projected points plus deterministic boom/bust probabilities, and keeps `half_ppr` available through the same scoring interface
- Added `/api/fantasy/predict` plus fantasy summary fields on `/api/slate` top picks, including component scoring, context factors, neutral injury/weather fallbacks, and omitted-stat reporting
- Updated dashboard player cards to show fantasy projection, boom %, bust %, and P10/P90 range while preserving the existing prop edge display
- Confirmed the app continues to use replay artifacts and `docs/synthetic_replay_props.csv`; no Odds API setup is required for the current synthetic analysis workflow
- Fixed the packed PyInstaller sidecar by importing the FastAPI app directly instead of relying on a dynamic `uvicorn` import string that omitted the local `api` package
- Updated the sidecar build script to prefer the repo `.venv` PyInstaller when available, and ignored local `.venv`, Tauri `target`, and generated schema folders
- Added route error/loading fallback pages so API startup and sidecar readiness failures show a clearer desktop message

**Verification:** `101 passed, 4 deselected` via `.\.venv\Scripts\python.exe -m pytest`; focused fantasy/API tests `12 passed`; `npm.cmd run build` passed; rebuilt sidecar served `/api/health` and `/api/slate` from replay artifacts.

---

## v0.5.0 - 2026-04-23

**Step 5 full desktop app: all pages, analyst SSE, .msi installer.**

- Built sidecar binary (`nfl-prop-api-x86_64-pc-windows-msvc.exe`, 11 MB) via PyInstaller
- Added nav bar to `App.tsx` with Dashboard and Parlay Builder links
- Added `desktop/src/routes/player-detail-page.tsx`: game log table, top projection DistChart, replay picks list, analyst panel toggle; click-through from dashboard PlayerCards
- Added `desktop/src/routes/parlay-builder-page.tsx`: pick cart, legs/stake controls, POST to `/api/parlays/build`, result display with ROI and EV
- Added `desktop/src/components/analyst-panel.tsx`: SSE streaming from `/api/analyst/stream`, tool-call collapsible chips, abort controller, animated cursor
- Added `api/routes/analyst.py`: async SSE endpoint forwarding tokens from llama.cpp `/v1/chat/completions`; graceful error if LLM not reachable
- Filled `WeatherBadge` (temp/wind/rain icons, aria-label) and `InjuryPill` (Q/D/O/IR/PUP color-coded, tooltip) components
- Installed all Radix UI primitives + recharts + tanstack/react-table + tanstack/react-query + framer-motion + date-fns + react-hook-form + zod + sonner + Playwright + axe-core (342 packages)
- Added `sse-starlette>=3.3.4` to Python deps
- Built `.msi` installer: `NFL Prop Predictor_0.5.0_x64_en-US.msi` (14 MB, target was <50 MB)

**Verification:** TypeScript 0 errors; `95 passed, 4 deselected` via `uv run pytest -q`; .msi 14 MB

---

## v0.4.7 - 2026-04-22

**Step 4 closeout: artifact contract frozen and Step 5 handoff documented.**

- Froze the replay artifact contract (picks/parlays CSV+JSON, summary JSON+MD, breakdown CSVs+JSONs) as the stable upstream interface for the Step 5 app and API layer
- Added frozen contract table and Step 5 handoff section to `docs/Step4Plan.md`
- Updated `api/settings.py:sample_props_path` to point to `docs/synthetic_replay_props.csv` as the API seed file
- Marked all `v0.4.7` tracker items complete in `docs/Step4Plan.md`

Step 4 is closed. Step 5 begins next.

**Verification:** `95 passed, 4 deselected` via `uv run pytest -q`

---

## v0.4.6 - 2026-04-22

**Step 4 full replay runs: synthetic props generator and complete 2024/2025 artifact package.**

- Added `scripts/generate_synthetic_props.py` to produce synthetic prop lines from each player's 4-game shifted trailing average (rounded to floor+0.5), covering all supported stat/position combinations for 2024 and 2025; outputs ~41,500 rows to `docs/synthetic_replay_props.csv`
- Generated full replay artifact packages for 2024, 2025, and combined 2024-2025 using the finalized replay pipeline and synthetic props file
- Added `tests/test_synthetic_props.py` with 9 tests covering line rounding, position gating, history filtering, schema validation, and odds column correctness
- Marked all `v0.4.6` tracker items complete in `docs/Step4Plan.md` and added replay results summary and interpretation section

Replay results (synthetic props baseline): 2024 ROI +9.8% on 16,935 bets; combined 2024-2025 ROI +5.9% on 36,360 bets. This is an engineering-gate result — lines were derived from the same nflverse data the models train on, so ROI measures model signal vs. trend-following, not profitability vs. real sportsbook lines. Strategy gate remains open pending real closing lines (Step 6).

**Verification:** `95 passed, 4 deselected` via `uv run pytest -q`

---

## v0.4.5 - 2026-04-22

**Step 4 replay hardening implemented: canonical contract, policy controls, and diagnostics artifacts.**

- Hardened `eval/calibration_pipeline.py` so local props files normalize `opp_team` into `opponent_team`, validate duplicate rows, support replay-required odds columns, and report skipped unsupported-stat, missing-odds, and missing-outcome rows instead of silently dropping them
- Expanded `eval/replay_pipeline.py` with stable Step 4 CLI filters (`--replay-years`, `--weeks`, `--stats`, `--books`), configurable pick caps, baseline comparisons, detailed validation metadata, breakdown generation, and richer JSON/Markdown replay summaries
- Extended `eval/prop_pricer.py` with explicit replay pick-policy enforcement for `min_edge`, stake sizing, max picks per week, max picks per player, and max picks per game, along with skip accounting for threshold and cap rejections
- Extended `eval/parlay_builder.py` so same-week parlays are grouped by season and week, include settled results and ROI stats, and remain separated from singles reporting while preserving conservative same-game and same-team penalties
- Added coverage for schema validation, opponent-field normalization, skipped-row accounting, replay filters, calibrator-enabled replay, policy caps, and artifact writing across `tests/test_calibration_pipeline.py`, `tests/test_prop_pricer.py`, and `tests/test_replay_pipeline.py`
- Updated `docs/Step4Plan.md` to mark the `v0.4.3` through `v0.4.5` implementation items complete and to lock the current default replay policy values

**Verification:** `80 passed, 4 deselected` via `uv run pytest -q`

---

## v0.4.3 - 2026-04-22

**Step 4 planning doc added: local replay-first tracking contract and handoff framework.**

- Added `docs/Step4Plan.md` as the supplementary active tracker for Step 4 execution without replacing `docs/plan.md`
- Locked Step 4 around a local historical props replay pipeline for 2024-2025, with The Odds API explicitly reserved as the planned live-season odds source
- Documented Step 4 definition of done, replay schema, CLI and artifact contracts, reporting goals, policy hardening work, and Step 5 through Step 7 handoff expectations
- Updated `docs/plan.md` so the macro roadmap reflects the local-replay-first Step 4 and live-ingestion Step 6 split

**Current project note:** Step 3 calibration remains an optional upgrade path during Step 4. Replay must run without a calibrator, but may consume one when a saved calibrator exists.

---

## v0.4.2 - 2026-04-22

**Step 2 accuracy iteration: added context-aware weekly features and revision-delta reporting.**

- Added shared weekly feature helpers in `models/feature_utils.py` so position models can reuse lagged rolling-rate and group-context feature engineering
- Improved `models/qb.py` with rolling efficiency features (`yards_per_attempt`, TD rate, INT rate, completion rate) plus lagged team passing context and opponent passing-defense context
- Improved `models/rb.py` with rolling efficiency features (`yards_per_carry`, TDs per carry) plus lagged team rushing context and opponent rushing-defense context
- Improved `models/wr_te.py` with rolling efficiency features (catch rate, yards per target, TDs per target) plus lagged team receiving context and opponent receiving-defense context
- Extended `eval/model_backtest.py` to preserve the prior saved metrics report long enough to generate explicit before/after revision comparisons
- Generated new comparison artifacts:
  - `docs/model_revision_comparison.json`
  - `docs/model_revision_comparison.md`
  - `docs/holdout_revision_comparison.json`
  - `docs/holdout_revision_comparison.md`
- Regenerated `docs/walk_forward_metrics.*` and `docs/holdout_metrics.*` with the updated models

**Measured result:** walk-forward and 2025 holdout MAE/RMSE improved modestly on most core volume stats, with the clearest gains in RB rushing volume and WR/TE receiving yards. Bias remains a follow-up area, especially for some QB/receiving outputs.

**Verification:** `75 passed, 4 deselected` via `uv run pytest -q`

---

## v0.4.1 - 2026-04-22

**Step 4 started: local paper-trade replay pipeline and parlay candidate generation.**

- Added local replay support in `eval/replay_pipeline.py` so a historical prop-lines file can be replayed end-to-end without waiting on live API wiring
- Extended `eval/prop_pricer.py` with two-sided market pricing, bet settlement, unit-profit math, paper-trade pick selection, and replay summaries
- Implemented a lightweight same-week parlay builder in `eval/parlay_builder.py` with conservative same-game/team penalties instead of naive independence
- Exposed `load_props_file(...)` from `eval/calibration_pipeline.py` so replay and calibration can share one local prop-line file format
- Added replay pipeline tests in `tests/test_replay_pipeline.py`

**Step 4 note:** this is a local historical replay path, not full Odds API historical wiring yet. It is intended to keep Step 4 moving while external historical player-prop access remains constrained.

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
