# Version History

Note: entries are listed newest first and oldest last.
Note: versioning follows `v0.x` or `v0.x.y`, where `x` maps to the numbered plan step in `docs/plan.md` for the current active work phase and optional `.y` is reserved for sub-updates within that active step. If work is currently under Step 4, then related fixes or improvements still version as `v0.4.y` until the active step changes.

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
