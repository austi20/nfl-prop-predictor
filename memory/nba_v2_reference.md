# NBABets v2 Reference Map

Where to find the canonical implementation when porting (repo: `E:\Projects\NBABets v2`).

## Trading (mostly sport-agnostic — port near-wholesale)
- `app/trading/loop.py` + `loop_controller.py` — supervised loop, preflight gate, watchdog, DB kill switch check per tick
- `app/trading/active_trader.py` + `portfolio_manager.py` — FSM: BUY_PENDING → HOLDING → SELL_PENDING
- `app/trading/market_book.py`, `ws_consumer.py`, `ws_disconnect_poller.py`, `snapshot_service.py` — live market data
- `app/trading/sql_ledger.py` + alembic migrations — durable ledger; `app/db/models/trading.py::TradingKillSwitch`
- `app/trading/readiness.py` — 7 live gates (symbol_resolved, fresh_market_snapshot, market_open, event_not_stale, spread_within_limit, one_order_cap_ok, price_within_limit)
- `app/trading/risk.py`, `live_limits.py`, `allocation.py` — risk limits + sizing
- `app/trading/decision_brain.py` — deterministic selection/gating/ranking; LLM advisory-only, downgrade-only
- `app/trading/paper_adapter.py` — Fake + Realistic paper adapters for rehearsal

## Models / training infra
- `app/training/calibration.py` — isotonic with collapse guards + sample-size bounding; `calibration_ece.py`
- `app/training/artifacts.py` — namespaced artifact registry
- `app/training/feature_cache.py`, `data_sufficiency.py`, `locked_defaults.py`, `ablation_grid.py`

## Brain / autonomy
- `app/services/brain/` — BrainStore (SQLite) + Obsidian vault bridge; safety caps: ≤20% weight change, ≤3 corrections/run, revert after 2 bad runs
- `app/services/agents/` — accuracy_examiner, data_quality, prediction_validator, parlay_advisor, control_plane
- Vault: `~/AI Brain/ClaudeBrain/05 Knowledge and Skills/Data Analysis/Kalshi Market Decision Brain/` (NBA). NFL gets its own sibling section.

## Desktop
- `desktop_tauri/scripts/generate-api.mjs` — openapi-typescript client gen from sidecar `/openapi.json`
- TanStack Router file routes; `useStartupSnapshot` + `/api/startup/snapshot`; TanStack Virtual for boards
- `app/server/routers/` — board, insights, parlays, props, startup, trading, local_agent

## Kalshi NBA series aliases (adapt for NFL)
`decision_brain.py`: points→KXNBAPTS, rebounds→KXNBAREB, assists→KXNBAAST, threes→KXNBA3PT, pra→KXNBAPRA. NFL needs equivalent series mapping discovery.

## Authority split (keep this invariant)
Deterministic scripts choose market/line/side/price gates/ranking. Vault stores policy/mappings/overrides/snapshots. LLM is advisory only, may only downgrade to hold/observe. Preflight + guarded runner are the final live gate.
