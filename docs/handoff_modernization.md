# Handoff: NFL Modernization, Phases 2–7

**For:** Claude Code (or any agent) working in `E:\Projects\NFLStatsPredictor`
**Read first:** `docs/modernization_plan.md` (gap analysis + phase order), `memory/nba_v2_reference.md` (file-level port map), `VERSIONS.md` (shipped history).
**Reference repo:** `E:\Projects\NBABets v2` — port its patterns; don't extend NFL legacy code.

## Phase 0–1 status — PROTOTYPED LOCALLY, NOT SHIPPED

A first cut of the durable-execution layer exists as **uncommitted** working-tree files
and is **not wired into the running app**:

- `api/db/__init__.py` + `api/db/models.py` — SQLite engine + SQLAlchemy models (`create_all`, no alembic).
- `api/trading/sql_ledger.py` (`SqlPortfolioLedger`) + `api/trading/kill_switch.py` (`SqlKillSwitch`).
- `tests/trading/test_sql_ledger.py` — 9 tests (fill math, durability, kill switch).

Still to do before this is real: add `sqlalchemy` to `pyproject.toml`; swap `ExecutionService`
onto the SQL ledger behind a `use_sql_ledger` setting; add `trading_db_path`; add kill-switch
status/reset routes; add ruff/mypy config. Only then log it in `VERSIONS.md`.

**First action:** `uv add sqlalchemy` then `uv run pytest -q tests/trading/` to confirm the
prototype still passes in-repo. Then continue Phase 1 wiring.

## Phase 2 — Readiness + loop supervision

Port from NBA v2:
- `app/trading/readiness.py` → `api/trading/readiness.py`. Keep the 7 gates (symbol_resolved, fresh_market_snapshot, market_open, event_not_stale, spread_within_limit, one_order_cap_ok, price_within_limit). NFL cadence is weekly: widen staleness windows (gate constants) accordingly.
- `app/trading/live_limits.py` → `api/trading/live_limits.py` (config-file-backed limits; put the JSON under `cache/` or `.env`-driven settings).
- `app/trading/loop_controller.py` → `api/trading/loop_controller.py`: subprocess spawn of a loop script, **preflight gate before start** (refuse to start if readiness fails), watchdog thread, blocked-state surface.
- New routes (mirror NBA `app/server/routers/trading.py`): `GET /trading/readiness`, `GET /trading/loop/status`, `POST /trading/loop/start`, `POST /trading/loop/stop`. Kill switch routes already exist.
- The loop body for now: poll quotes for monitored markets via the existing `api/trading/kalshi/client.py`, mark-to-market the SqlPortfolioLedger, check kill switch each tick (pattern: NBA `loop.py::_kill_switch_active`).

Tests: readiness gate unit tests (each gate pass/fail), controller start-blocked-on-preflight, kill-switch tick check. NOTE: SQLite tests must not write under the repo `tmp/` if run in a Linux sandbox (mount can't lock); use real `tmp_path` or a local dir.

## Phase 3 — Live market data + ActiveTrader

- Wire existing `api/trading/kalshi/ws.py` into ported `ws_consumer.py`, `ws_disconnect_poller.py`, `market_book.py`, `snapshot_service.py` (NBA `app/trading/`).
- Port `portfolio_manager.py` (FSM: BUY_PENDING → HOLDING → SELL_PENDING) and `active_trader.py` (entry gates over `CandidateProvider`; candidates come from `eval/` PropDecisions).
- Port `allocation.py` for stake sizing.
- Rehearse exclusively against `RealisticPaperAdapter` — no live order path until Phase 4's deterministic gates + preflight exist.

## Phase 4 — Decision brain

- Port the *pattern* of NBA `decision_brain.py` (~2k lines — port incrementally): deterministic market/line/side selection, price gates, row-zero ranking. Replace `_KALSHI_PLAYER_PROP_SERIES_BY_ALIAS` (KXNBAPTS etc.) with NFL series — discover current tickers via Kalshi API before hardcoding.
- LLM advisory layer: reuse `llm/` (Qwen, `/v1/chat/completions`). **Invariant: LLM may only downgrade to hold/observe — never upgrade or change selection.**
- Port `selections.py` (SelectionStore) and `live_pack_builder.py`.
- Vault bridge: NBA writes to `~/AI Brain/ClaudeBrain/05 Knowledge and Skills/Data Analysis/Kalshi Market Decision Brain/`. Create a sibling `Kalshi NFL Decision Brain` section; same frontmatter statuses (`candidate`, `selected_observe_only`, `selected_live`; blocking: `blocked`, `disabled`, `manual_review`, `postmortem_ready`).

## Phase 5 — Model infrastructure

- Keep `models/dist_family.py` GLMs. Port NBA `app/training/calibration.py` (isotonic with collapse guards + sample-size bounding) + `calibration_ece.py` into `eval/`, replacing the bare isotonic/Platt in `prop_pricer.py`.
- **Blocker to clear first:** real Kalshi quote capture (settings flag `use_calibration` stays False until fit on captured real lines — see `docs/ModelingNotes.md` "Phase H5 calibration deferral"). Build a quote-capture job that snapshots NFL prop quotes into SQLite/parquet; Phase 2's loop is the natural host.
- Port `artifacts.py` (namespaced artifact registry), `feature_cache.py`, `data_sufficiency.py` patterns into `models/`/`eval/` as fits.

## Phase 6 — Desktop modernization

- Copy `desktop_tauri/scripts/generate-api.mjs` from NBA v2 → `desktop/scripts/`; add `openapi-typescript` devDep + `"generate-api"` script; replace the hand-written client in `desktop/src/lib/`.
- Migrate react-router-dom → TanStack Router (NBA `desktop_tauri/src/routes/` shows the file-route layout).
- Add `/api/startup/snapshot` endpoint + `useStartupSnapshot` hook (NBA pattern) for fast first paint.
- Add a `trading` route group: loop status, readiness gate panel, portfolio (now durable), kill-switch trip/reset buttons (endpoints exist).
- Add `@tanstack/react-virtual` on slate/board tables. React 18→19 bump last, after tests pass.
- Prune unused deps (embla, vaul, cmdk, framer-motion, most Radix pkgs) only if actually unused — check imports first.

## Phase 7 — Brain + agents (last)

- Port `app/services/brain/` (BrainStore SQLite + vault bridge + outcome collector). Keep safety caps exactly: ≤20% weight change, ≤3 corrections/run, revert after 2 bad runs, ≥5 samples per strategy.
- Then agents: accuracy_examiner, data_quality, prediction_validator first; control plane later.

## Conventions (repo rules)

- uv, Python ≥3.13; `uv run pytest -q`; secrets in `.env`; deps in `pyproject.toml`.
- Log each shipped phase in `VERSIONS.md` (newest first), version as `v0.9-m<phase>`.
- Durable notes → `memory/`; generated artifacts → `cache/` or `docs/`.
- KISS: smallest correct change; alembic only when the DB schema starts churning.
