# NFL → NBABets v2 Modernization Plan

**Date:** 2026-06-10 (gap analysis); phases 0-7 not yet started as of v0.9.0.
**Source of truth for the target architecture:** `E:\Projects\NBABets v2`

NBABets v2 is the same product idea (props engine → Kalshi execution → desktop app) one full generation ahead. Most of its trading layer is sport-agnostic and portable. This doc is the gap analysis and the migration order.

---

## 1. Gap analysis

### 1.1 Desktop app / UI

| Area | NFL (current) | NBA v2 (target) |
|---|---|---|
| Shell | Tauri 2 + React 18 | Tauri 2 + React 19 |
| Routing | react-router-dom 7, hand-wired | TanStack Router (typed routes: index, players, parlays, insights, settings, trading/*) |
| API client | hand-written | **openapi-typescript generated** from sidecar `/openapi.json` (`scripts/generate-api.mjs`, `npm run generate-api`) |
| Data fetching | TanStack Query | TanStack Query + **TanStack Virtual** for big boards |
| Startup | ad hoc | `useStartupSnapshot` hook + `/api/startup/snapshot` endpoint (single startup payload, fast first paint) |
| Dep weight | full shadcn Radix set (~25 Radix pkgs), framer-motion, embla, vaul, cmdk | 3 Radix primitives, lean |
| Dev aids | — | `dev.components.tsx` route (component gallery) |

NFL's dep versions are partly *newer* (Vite 8, Vitest 4) — keep those. The gap is architectural: generated typed API client, typed router, virtualization, a startup snapshot, and a dedicated trading route group (loop status, readiness, kill switch).

### 1.2 Model logic

| Area | NFL | NBA v2 |
|---|---|---|
| Core models | statsmodels GLMs per position (Poisson/NegBin/Gamma/Beta, quantile, decomposed MC) | sklearn HistGradientBoosting + Ridge (+ optional XGBoost), TimeSeriesSplit, MinutesModel + StatModelSuite |
| Calibration | isotonic + Platt in `eval/prop_pricer.py`, **never fitted on real lines**, `use_calibration=False` | `ProbabilityCalibrator` with isotonic-collapse guards, sample-size probability bounding, ECE tracking (`calibration_ece.py`) |
| Config locking | locked defaults hard-coded in each model's `fit()` (Phase H) | `locked_defaults.py` + `ablation_grid.py` as first-class modules |
| Artifacts | joblib save/load per model | `artifacts.py` with namespace resolution, existence checks |
| Data hygiene | preflight guards in train scripts | `feature_cache.py`, `data_sufficiency.py`, model_quality service, simulation_context |

Verdict: NFL's GLM family layer (`dist_family.py`) is good domain modeling — don't throw it away for GBMs. Port the *infrastructure*: calibrator guardrails + ECE, artifact registry, feature cache, sufficiency gates. The v0.9 blocker remains real-quote capture (calibration on synthetic surrogate odds is why `use_calibration` stayed False).

### 1.3 Trading loop and execution

This is the biggest gap. NFL execution is request-driven and ephemeral; NBA v2 is a persistent, supervised, stateful trading system.

| Capability | NFL | NBA v2 |
|---|---|---|
| Loop | none — `ExecutionService.submit_picks()` one-shot | `TradingLoop` + `TradingLoopController` (subprocess spawn, **preflight gate before start**, watchdog, blocked-state reporting) |
| Active trading | none | `ActiveTrader` FSM (`BUY_PENDING → HOLDING → SELL_PENDING`) over `MarketBook` + `PortfolioManager` |
| Market data | `kalshi/ws.py` exists, unused by any loop | `ws_consumer` + `ws_disconnect_poller` + `ws_frames` + `live_stats_poller` + `snapshot_service` |
| Ledger | `InMemoryPortfolioLedger` only | `sql_ledger.py` (SQLAlchemy + alembic migrations) — survives restarts |
| Kill switch | in-process protocol | **DB-backed** `TradingKillSwitch` row (killed/flatten), checked every loop tick, trippable from UI |
| Risk | `StaticRiskEngine`/`ExposureRiskEngine` | same lineage plus `RiskLimits`, `live_limits.py` config, `allocation.py` |
| Readiness | none | `readiness.py` — 7 live gates: symbol_resolved, fresh_market_snapshot, market_open, event_not_stale, spread_within_limit, one_order_cap_ok, price_within_limit |
| Decision layer | model edge → pick | `decision_brain.py` (~2k lines): deterministic scripts pick market/line/side/price gates/ranking; **local LLM is advisory-only and can only downgrade** to hold/observe; preflight + guarded runner are the final gate |
| Monitoring | telemetry (OTel) | `monitoring.py` quote snapshots, `stream_publisher`, paper adapters (fake + realistic) for rehearsal |

### 1.4 Autonomy / brain / agents

NFL has none of this layer. NBA v2 has:

- `app/services/brain/` — persistent learning: SQLite `BrainStore` + Obsidian vault bridge (`~/AI Brain/ClaudeBrain/05 Knowledge and Skills/Data Analysis/Kalshi Market Decision Brain/`). Safety caps: max 20% weight change, max 3 corrections/run, auto-revert after 2 bad runs, min 5 samples per strategy.
- `app/services/agents/` — accuracy examiner, data quality, prediction validator, parlay advisor, api monitor, control plane, router.
- `app/services/local_autonomy/` — engine, overfit intel, policy state, debug copilot.
- `memory/*.md` — repo-level durable notes (e.g. `kalshi_decision_brain.md`).
- `.claude/` — CLAUDE.md, 7 role agents, 6 skills, 3 hooks (protected-path blocking, post-edit quality, config-change audit).

### 1.5 Repo hygiene

NFL: pytest only; no ruff/mypy config; no DB/migrations; no CLAUDE.md. NBA v2: ruff + mypy + pytest + `scripts/check.ps1`, alembic, guarded `.claude` setup.

---

## 2. Migration plan (ordered, each phase shippable)

**Phase 0 — Foundations (small, do first)**
Add ruff + mypy config to `pyproject.toml`; add SQLAlchemy + alembic with a `trading` schema (ledger, kill switch, selections); port `.claude/` (CLAUDE.md now created, then hooks/skills/agents as needed); create `memory/` for durable notes.

**Phase 1 — Durable execution**
Port `sql_ledger.py`, DB-backed `TradingKillSwitch`, `live_limits.py`. Swap `ExecutionService` onto the SQL ledger. NFL's adapter protocols (`api/trading/adapters.py`) already mirror NBA v2's `protocols.py`, so this is mostly drop-in.

**Phase 2 — Readiness + loop supervision**
Port `readiness.py` (7 live gates, re-keyed to Kalshi NFL series) and `loop_controller.py` (preflight-gated subprocess + watchdog). Expose `/api/trading/loop` + readiness endpoints; UI gets a trading route with start/stop/kill and gate status.

**Phase 3 — Live market data + ActiveTrader**
Wire the existing `api/trading/kalshi/ws.py` into ported `ws_consumer`/`ws_disconnect_poller`/`market_book`/`snapshot_service`. Port `PortfolioManager` FSM + `ActiveTrader` + `allocation.py`. Rehearse on `RealisticPaperAdapter` before any live mode.

**Phase 4 — Decision brain**
Port `decision_brain.py` pattern: deterministic market/line/side selection + price gates + row-zero ranking; local LLM (Qwen integration already exists in `llm/`) advisory-only with downgrade-only authority; selections store; live pack builder; vault bridge to a new `Kalshi NFL Decision Brain` section in the AI Brain vault.

**Phase 5 — Model infrastructure**
Keep GLM family layer. Port `ProbabilityCalibrator` guardrails + ECE, `artifacts.py` namespacing, `feature_cache.py`, `data_sufficiency.py`. Unblock calibration by shipping real Kalshi quote capture (the deferred v0.9 item) and fit on captured lines, not synthetic surrogates.

**Phase 6 — Desktop modernization**
Add `generate-api.mjs` (openapi-typescript) and replace the hand-written client; migrate react-router-dom → TanStack Router; add TanStack Virtual on slate/board tables; add `/api/startup/snapshot` + `useStartupSnapshot`; React 19; prune unused Radix/animation deps; add trading routes (loop, readiness, portfolio, kill switch).

**Phase 7 — Brain + agents**
Port `BrainStore` + vault bridge + outcome collector with the same safety caps; then agents (accuracy examiner, data quality, prediction validator) and local autonomy engine as value proves out.

**Porting note:** `app/trading/` in NBA v2 is ~90% sport-agnostic. NFL-specific work is the symbol/series mapping (KXNBA* → NFL series), prop-stat aliases, and schedule cadence (weekly slates vs nightly — relaxes staleness/polling constants).

---

## 3. What NOT to copy

- NBA v2's GBM stack — NFL's GLM distribution families are better suited to weekly low-n football counts (NegBin fallback logic in `dist_family.py` exists for a reason).
- NBA v2's nightly-cadence polling constants — NFL is weekly; retune staleness windows.
- The `.tmp_*` clutter and worktree sprawl — keep NFL's repo clean.
