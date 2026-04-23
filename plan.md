# Plan: Post-Step-5 Hardening → Trading Framework (stub) → Model Training + Historical Weather

## Context

Step 5 shipped at v0.5.1. The Tauri app installs from .msi, sidecar boots on an ephemeral port, dashboard/player-detail/parlay-builder routes render, analyst SSE streams tokens. The shell is coherent but visibly pre-enterprise: Vite-template README/title leak through, CSP is disabled, CORS is wildcard, weather/injury badges render `null`, React Query is installed but unused, analyst frontend listens for a `tool_call` event the backend never emits.

Today is 2026-04-23. NFL season kicks off ~Sept 2026. That's a ~4.5-month offseason window where the highest-leverage work isn't exchange plumbing — it's **model training on expanded history**. The repo's differentiator is the position models, shrinkage calibration, and replay pipeline, not the venue connectors. Kalshi demo and Polymarket can't do a useful end-to-end validation until live NFL markets exist.

Reprioritized plan:
1. **Harden the workstation (v0.6a+b+c)** — fix the pre-enterprise leaks, wire React Query, align SSE contract, replace placeholder UX, WCAG 2.2 AA sweep. Full implementation. No season dependency.
2. **Trading domain model (v0.7a)** — full implementation: venue-agnostic `Signal`, `MarketRef`, `ExecutionIntent`, `RiskDecision`, `OrderEvent`, `PortfolioState`, audit log, risk engine, ledger, mapper, pricing. Pure code.
3. **Paper trading + Kalshi SCAFFOLD (v0.7b-scaffold, v0.8a-scaffold)** — real UI surface, real routes, real audit trail, real kill switch, real secret vault, real signing test. Adapters and network calls are fakes/stubs until season opens. Shape committed so later swap-in is mechanical.
4. **Model training + historical weather (v0.8b+c+d)** — backfill Open-Meteo archive weather for every game 2018–2025, add weather features to the three position GLMs, expand replay scope, sweep shrinkage `k` (currently hardcoded 8), recalibrate probability outputs. This is where the offseason time goes.

Polymarket (global V2 + US) and live-money automation remain **out of scope**, gated behind a future v0.9 phase after the season validates the scaffolding.

Outcome: repo exits this work with a production-shaped local workstation, a full trading domain committed as code, exchange integrations scaffolded for in-season completion, and a materially stronger model trained on 8 seasons × real weather.

---

## Phase A — v0.6a: Workstation Leaks Fixed

Small, visible fixes. Each one is ≤1 file.

### A1. Replace the Vite template leaks

**Modify:**
- `desktop/index.html` — change `<title>desktop</title>` to `<title>NFL Prop Workstation</title>`.
- `desktop/README.md` — rewrite to a short "what this is, how to run dev, how to build" doc matching the repo's main README tone. ~40 lines max.

### A2. Tighten Tauri CSP

**Modify:** `desktop/src-tauri/tauri.conf.json` — set `app.security.csp` to a real policy:
```
"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*; img-src 'self' data:"
```
Loopback `connect-src` is needed because the sidecar port is ephemeral. `unsafe-inline` on `style-src` is required by Tailwind 4's generated styles; no `unsafe-inline` on scripts.

**Verify:** `npm run tauri dev`; dashboard still loads; devtools Console is clean of CSP violations.

### A3. Scope CORS on the sidecar

**Modify:** `api/server.py` — replace wildcard origins with `["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"]`. Keep `allow_credentials=False`.

**Verify:** `uv run pytest -q tests/test_api_*` passes; Tauri dev window loads `/api/slate` without CORS errors.

### A4. Align the analyst SSE contract

**Modify:**
- `api/routes/analyst.py` — when the llama.cpp response contains a tool-call delta, emit an SSE frame with `event: tool_call` and payload `{name, args}`. Pass through existing `token`/`error`/`complete` unchanged.
- `desktop/src/components/analyst-panel.tsx` — handle the `error` event from the server payload (currently only surfaces fetch-level failures); render tool-call chips collapsibly.

**Test:** `tests/test_analyst_stream.py` — one case mocks the llama.cpp client yielding a tool-call delta and asserts the SSE output contains the `tool_call` frame.

### A5. Wire React Query for route data

`@tanstack/react-query@^5.100.1` is installed but unused.

**Modify:**
- `desktop/src/main.tsx` — wrap the router in `QueryClientProvider` with a shared client.
- `desktop/src/routes/dashboard-page.tsx`, `player-detail-page.tsx`, `parlay-builder-page.tsx` — convert to `useQuery({ queryKey, queryFn: () => api.getX() })`. Delete the `*-loader.ts` files.
- `desktop/src/router.tsx` — drop `loader:` properties.

Keep API functions in `desktop/src/lib/api.ts` — hooks wrap them, don't replace them.

**Verify:** `npm run build` succeeds; all pages render; stale-click on a player card returns instantly from cache.

**Git checkpoint:** update `VERSIONS.md` with v0.6a entry; tag `v0.6a`.

---

## Phase B — v0.6b: Beginner UX + Honest Placeholders

The dashboard is analyst-grade. Beginners bounce off it. No redesign; just relabel, fill in, add guidance.

### B1. Replace dev-facing language

**Modify:** `desktop/src/routes/dashboard-page.tsx` — any "Step N" / replay phase IDs / internal version strings become plain English.

### B2. Make the Filters card actually filter

**Modify:** `desktop/src/routes/dashboard-page.tsx` — read-only Filters block becomes real controls: position multi-select, min edge slider, stat multi-select. State is local (`useState`); filtering runs client-side against the React Query cache. Safe defaults: all positions on, min edge 0, all stats on.

### B3. Honest placeholders

**Modify:** `desktop/src/components/player-card.tsx` — `weather === null` renders `"No current feed"` (muted pill), not `"Weather N/A"`. `injury === null` renders `"Status unknown"`, not `"Active"`.

**Defer wiring** of live weather/injury data to Phase I (Phase G's historical-weather backfill + Phase I's live wiring handles both the training feature and the UI surface in one pass). Ship the UI with honest null states now.

### B4. Analyst starter prompts

**Modify:** `desktop/src/components/analyst-panel.tsx` — empty input shows 3 starter chips: "Explain this pick in plain English", "Why over instead of under?", "What would change this recommendation?". Click → fills the input.

**Modify:** `desktop/src/routes/player-detail-page.tsx` — pass the current pick's `stat` + `line` into the analyst panel as props (the API already accepts them).

### B5. Glossary tooltips

**New file:** `desktop/src/components/glossary-tooltip.tsx` — CVA-styled tooltip, definition dictionary in the same file, ~60 lines. Terms: edge, ROI, EV, implied probability, fair odds, vig, boom/bust, shrinkage. Used on dashboard KPI labels and the parlay summary card.

### B6. WCAG 2.2 AA sweep

Install `@axe-core/playwright` as a devDependency. Add `desktop/tests/a11y.spec.ts` asserting zero axe violations at `wcag22aa` on each route.

**Verify:** `npx playwright test desktop/tests/a11y.spec.ts` → zero violations on dashboard, player detail, parlay builder.

**Brain checkpoint:** save a feedback note about "honest placeholders over confident-looking `null`s" — it should apply to future UI work.
**Git checkpoint:** update `VERSIONS.md` with v0.6b entry; tag `v0.6b`.

---

## Phase C — v0.6c: Telemetry + Frontend Test Baseline

### C1. Structured error envelopes

**Modify:** `api/server.py` — add a FastAPI `exception_handler` that wraps responses in `{success, data, error: {code, message, request_id}}`. Existing handlers stay; this intercepts only uncaught exceptions and HTTPExceptions.

**Modify:** `desktop/src/lib/api.ts` — fetch wrapper unwraps the envelope; surfaces `error.message` + `error.code` to callers. React Query handles retry.

### C2. Persisted operator settings

**Modify:** `desktop/src/store/app-store.ts` — use `zustand/middleware`'s `persist` with `localStorage`. Key: `nfl-prop-workstation:prefs`. Slice: theme, min-edge default, default stat filter, simple-vs-pro mode.

### C3. OpenTelemetry traces

**Modify:** `api/server.py` + `pyproject.toml` — add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`. Tracer writes spans to `docs/telemetry/spans-<date>.jsonl`. No external OTLP endpoint.

**New file:** `api/telemetry.py` — ~40 lines of setup. One span per request; child span per model evaluation; one span per analyst streaming session with token count.

### C4. Frontend test baseline

Python layer has ~80 tests; React layer has effectively none.

- **Install:** `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event` as devDeps.
- **New files:**
  - `desktop/vitest.config.ts`
  - `desktop/src/test/setup.ts`
  - `desktop/src/routes/__tests__/dashboard-page.test.tsx` — mocked `/api/slate`, filter controls update visible rows.
  - `desktop/src/routes/__tests__/parlay-builder-page.test.tsx` — cart add/remove, Build click posts to mocked endpoint.
  - `desktop/src/components/__tests__/analyst-panel.test.tsx` — SSE token rendering, abort, tool_call chip.
- **Modify:** `desktop/package.json` — `"test": "vitest run"`, `"test:watch": "vitest"`.

**Verify:** `cd desktop && npm test` — all pass.

**Brain checkpoint:** save a project note logging v0.6 close — boundary between "replay analytics client" and "trading-capable workstation."
**Git checkpoint:** update `VERSIONS.md` with v0.6c entry; tag `v0.6c`.

---

## Phase D — v0.7a: Generic Execution Domain (full implementation)

Venue-agnostic middle layer. Pure code, no season dependency.

### D1. Domain types

**New files in `api/trading/`:**
- `types.py` — frozen dataclasses/pydantic models:
  - `Signal`(`pick_id`, `player_id`, `stat`, `line`, `selected_side`, `modeled_prob`, `edge`, `created_at`)
  - `MarketRef`(`venue`, `market_id`, `ticker`, `tick_size`, `min_size`, `yes_token`, `no_token`)
  - `ExecutionIntent`(`signal_id`, `market_ref`, `side`, `limit_price`, `size`, `client_order_id`, `expires_at`)
  - `RiskDecision`(`intent_id`, `approved`, `reason`, `caps_snapshot`)
  - `OrderEvent`(`intent_id`, `event_type: submitted|acked|filled|partial|canceled|rejected`, `venue_order_id`, `price`, `size`, `ts`)
  - `PortfolioState`(`cash_balance`, `positions: dict[market_id, Position]`, `realized_pnl`, `unrealized_pnl`)
- `audit.py` — append-only JSONL writer at `docs/audit/events-<date>.jsonl`. Single `log_event(kind, payload)`. Write-forward, no reads.

### D2. Adapter Protocols

**New file:** `api/trading/adapters.py` — `typing.Protocol` classes: `MarketDiscoveryAdapter`, `SignalMapper`, `RiskEngine`, `OrderRouter`, `MarketDataStream`, `OrderStatusTracker`, `PortfolioLedger`, `KillSwitch`. Duck-typed over ABCs so tests pass lightweight fakes.

### D3. Risk engine

**New file:** `api/trading/risk.py` — `StaticRiskEngine` implementing `RiskEngine`. Caps: max notional per order, max open notional per market, daily loss cap, cooldown after N rejects in M seconds, min edge to route. Configured via `api/settings.py` with `NFL_APP_RISK_*` prefix.

**Test:** `tests/trading/test_risk.py` — one case per cap; kill-switch trips after 3 rejects in 60s.

### D4. Portfolio ledger

**New file:** `api/trading/ledger.py` — `InMemoryPortfolioLedger` applies `OrderEvent`s in sequence. `filled` updates cash + position; `canceled` releases reservation. Snapshots to `docs/audit/portfolio-<session>.json` on every change.

**Test:** `tests/trading/test_ledger.py` — buy→fill, partial fill, cancel, position math.

### D5. Pricing + mapper

**New file:** `api/trading/pricing.py` — American odds → CLOB price in `[0, 1]` with a clear docstring. One conversion function both Kalshi and Polymarket-style venues use.

**New file:** `api/trading/mapper.py` — `PickToIntentMapper` takes a Pick + pre-built `markets: list[MarketRef]` and emits an `ExecutionIntent` if a match exists. Discovery is deferred to per-venue adapters.

**Test:** `tests/trading/test_pricing.py` — American −110 ≈ 0.524, +120 ≈ 0.455, boundary cases.

**Brain checkpoint:** project note summarizing the trading domain boundary — what's in `api/trading/` vs `api/services/`.
**Git checkpoint:** update `VERSIONS.md` with v0.7a entry; tag `v0.7a`.

---

## Phase E — v0.7b-scaffold: Paper Trading Surface (fake adapter)

Real UI surface, real routes, real audit, real kill switch. **Paper adapter is a trivial fake** — upgraded later in-season without touching callers.

### E1. Fake paper adapter

**New file:** `api/trading/paper_adapter.py` — `FakePaperAdapter` implements all adapter Protocols. Submission immediately emits `submitted` then `filled` at the limit price for every valid intent. `rejected` only if price is outside `[0, 1]` or size ≤ 0. No order-book simulation, no jitter, no synthetic market seed file. ~80 lines. Logs a warning on first use: "fake paper adapter active — fills are not realistic."

**Test:** `tests/trading/test_paper_adapter.py` — submit→fill, rejected-price, cancel.

### E2. Execution service + routes (full)

**New file:** `api/services/execution_service.py` — orchestrates: pick → mapper → risk → router → ledger, writes audit events. Exposes `submit_pick(pick_id)`, `cancel(intent_id)`, `get_portfolio()`, `get_events(since?)`, `trip_kill_switch(reason)`.

**New file:** `api/routes/execution.py`:
- `POST /api/execution/paper/submit` — body `{pick_ids: [...]}`
- `POST /api/execution/paper/cancel` — body `{intent_id}`
- `POST /api/execution/kill` — body `{reason}`
- `GET /api/execution/portfolio`
- `GET /api/execution/events`
- `GET /api/execution/events/stream` — SSE tail

**Modify:** `api/server.py` — register router.

### E3. Execution route (full UI surface)

**New file:** `desktop/src/routes/execution-page.tsx` — three panels:
- Left: pick queue from `/api/slate`, each with Submit.
- Middle: open intents + orders, with Cancel.
- Right: portfolio (cash, positions, realized/unrealized P&L) + audit event tail via SSE.

Persistent top banner: **"Paper mode — no real money"**. Green.

**Modify:**
- `desktop/src/App.tsx` — add nav link "Execution (Paper)".
- `desktop/src/router.tsx` — add `/execution` route.
- `desktop/src/lib/api.ts` — add `executionApi.submitPicks`, `cancel`, `getPortfolio`, `kill`, `eventsStream`.

### E4. Kill switch UI (full)

Big red button on the Execution page wired to `POST /api/execution/kill`. Tripping also cancels all open intents via `cancel_all()` on the adapter.

**Test:** Playwright e2e — submit 3 picks → kill → all flip to `canceled` in audit tail.

### E5. Frontend tests

`desktop/src/routes/__tests__/execution-page.test.tsx` — submit, cancel, kill-switch, banner always visible.

**Git checkpoint:** update `VERSIONS.md` with v0.7b-scaffold entry; tag `v0.7b-scaffold`.

---

## Phase F — v0.8a-scaffold: Kalshi Framework (no live calls)

Venue plumbing shape committed. No real Kalshi network calls. UI reflects "Coming in-season."

### F1. Kalshi module scaffold

**New files:**
- `api/trading/kalshi/__init__.py`
- `api/trading/kalshi/client.py` — `KalshiClient` class with method signatures matching the real client's future shape: `list_markets`, `place_order(intent)`, `cancel_order(venue_order_id)`, `get_order(venue_order_id)`, `get_balance`. All network-touching methods raise `NotImplementedError("Kalshi scaffold — activate in-season")`. Signing helper is **real** (F3).
- `api/trading/kalshi/adapter.py` — `KalshiAdapter` implementing Protocols from D2 by delegating to `KalshiClient`. Because the client raises, the adapter raises too — but class wiring, type signatures, and `client_order_id` handling are in place.
- `api/trading/kalshi/ws.py` — WebSocket listener stub. Class defined, auth-header construction present and tested, but `connect()` raises `NotImplementedError`.

### F2. Secret vault (full)

**New file:** `api/trading/secrets.py` — `keyring` wrapper: `store(venue, key_name, value)`, `load(venue, key_name)`, `delete(venue, key_name)`. Full implementation — the vault is useful before any venue goes live and costs nothing.

**New route:** `api/routes/secrets.py` — `POST /api/secrets/kalshi` stores access key + private key PEM. Requires a local-only confirmation token printed to the sidecar log at startup. Does not return values back.

**Modify:** `pyproject.toml` — add `keyring` dep.

**Test:** `tests/trading/test_secrets.py` — store→load round-trip using a pytest keyring backend.

### F3. RSA-PSS signing (full, testable without network)

**New file:** `api/trading/kalshi/signing.py` — `sign_request(private_key_pem, timestamp_ms, method, path) -> str` returning base64 PSS signature over `f"{timestamp_ms}{method}{path}"`.

**Test:** `tests/trading/test_kalshi_signing.py` — generates a test RSA keypair, signs a known request, verifies with the public key using `cryptography.hazmat.primitives.asymmetric.padding.PSS`. Proves the signing algorithm independently of any Kalshi account.

### F4. Kalshi mapper stub

**Modify:** `api/trading/mapper.py` — add `KalshiMapper`. `map_signal(signal, markets)` returns `None` and logs audit event `{kind: "mapping_skipped", venue: "kalshi", reason: "scaffold"}`. Real ticker-matching logic goes here in-season.

### F5. Execution page: venue selector (disabled)

**Modify:** `desktop/src/routes/execution-page.tsx` — add venue selector dropdown: "Paper" (default) / "Kalshi (Demo) — Coming preseason" (disabled). Disabled tooltip explains why. No code path activates; scaffolding just declares intent.

### F6. Docs

**New file:** `docs/TradingOps.md` — one page. Paper vs demo vs live, how to provision a Kalshi demo account when the time comes, secret-vault usage, kill-switch semantics, audit log location, compliance disclaimers. Kalshi section marked **"Scaffold only — activation pending v0.8a-live"**.

**Brain checkpoint:** feedback note — Kalshi adapter shape is frozen now; in-season activation is swapping `NotImplementedError` for real HTTP calls in `kalshi/client.py`, no callers change.
**Git checkpoint:** update `VERSIONS.md` with v0.8a-scaffold entry; tag `v0.8a-scaffold`.

---

## Phase G — v0.8b: Historical Weather Backfill

Open-Meteo's Archive API (ERA5 reanalysis) has hourly data from 1940 to ~5 days ago, free, no key. Same JSON shape as their forecast API. This phase backfills every NFL game 2018–2025 with actual kickoff-hour weather so models can train on it and replays use faithful conditions.

### G1. Stadium coordinate table

**New file:** `data/stadium_coords.py` — hand-maintained dict keyed by team abbreviation (and legacy codes where franchises relocated: OAK→LV, SD→LAC, STL→LAR, WAS old name, etc.). Fields: `lat`, `lon`, `altitude_ft`, `is_dome`, `is_retractable`, `tz` (IANA zone). 32 current teams + historical variants. ~60 lines of data.

Reuse the existing `DOME_TEAMS` frozenset in `data/nflverse_loader.py:26-37` as the authoritative dome list; extend to retractables and import here.

**Test:** `tests/test_stadium_coords.py` — every team in `nflverse_loader.load_schedules(2018..2025).home_team.unique()` has an entry; no missing IANA zones.

### G2. Weather backfill script

**New file:** `scripts/backfill_weather.py`:
- Load schedules via `data.nflverse_loader.load_schedules([2018..2025])`.
- For each game row: resolve `home_team` → stadium coords via G1; combine `gameday` + `gametime` (nfl_data_py schedules exposes both) into a UTC kickoff datetime using the stadium's IANA zone.
- Skip domes and closed retractables (output row has `weather_indoor=True`, no API call).
- For outdoor games, call Open-Meteo Archive:
  ```
  https://archive-api.open-meteo.com/v1/archive
    ?latitude={lat}&longitude={lon}
    &start_date={date}&end_date={date}
    &hourly=temperature_2m,precipitation,wind_speed_10m,wind_direction_10m,weather_code
    &timezone=UTC
  ```
- Extract the hour closest to kickoff. Respect Open-Meteo's free-tier rate limit (10k/day); throttle with `time.sleep(0.1)` between calls. ~2200 outdoor games × 8 seasons completes in ~5 minutes.
- Cache output at `data/cache/weather_archive.parquet` with columns: `game_id, season, week, home_team, kickoff_utc, temp_f, wind_mph, wind_dir_deg, precip_in, weather_code, indoor`.
- Idempotent: re-runs only fetch rows missing from cache.

**CLI:**
```
uv run python scripts/backfill_weather.py --seasons 2018,2019,2020,2021,2022,2023,2024,2025 \
  --out data/cache/weather_archive.parquet
```

**Test:** `tests/test_weather_backfill.py` — mock Open-Meteo HTTP; assert one dome game and one outdoor game produce correct rows (indoor short-circuits without network).

### G3. Weather loader integration

**Modify:** `data/weather.py` (currently a 2-line stub) —
- `load_archive(seasons: list[int]) -> pd.DataFrame` reads the parquet cache.
- `load_forecast(game_id: str) -> dict | None` hits the Open-Meteo Forecast API for upcoming games only (called in-season by the UI). Out-of-season returns `None`.
- Both paths share the same output schema.

**Modify:** `data/nflverse_loader.py` — add `load_weekly_with_weather(seasons)` that left-joins the weekly player-stats frame against the weather archive by `game_id`. Non-outdoor games get `indoor=True` and null weather columns. This is the frame the models consume.

**Brain checkpoint:** project note on weather-backfill cache location and schema so future replays pick it up automatically.
**Git checkpoint:** update `VERSIONS.md` with v0.8b entry; tag `v0.8b`.

---

## Phase H — v0.8c: Walk-Forward Training Loop + Calibration

Per-season walk-forward training driven by a **deterministic harness**, not the LLM. Qwen3 1.7B's role is narration only: structured template-fill into brain notes after each season completes. This phase focuses on **statistical accuracy**, not prop calculations.

**Why walk-forward:** training on year N → holdout-testing on N+1 → advancing is the correct methodology for time-series models. Prevents leakage that plain k-fold CV allows.

**Why deterministic loop, not LLM-driven:** 1.7B cannot reliably judge statistical quality; LLM-iterated tuning leaks the holdout into training via multiple-comparisons. Loop stops on numeric criteria. LLM writes the notes, never decides.

### H1. Weather features (flag-guarded) + training harness

**Modify:** `models/qb_model.py`, `models/rb_model.py`, `models/wr_te_model.py` — `_build_features(df, *, use_weather: bool = True)` adds (for outdoor games only; zero otherwise):
- `wind_mph` — affects passing_yards, passing_tds most
- `precip_in_kickoff_hour` — affects completions, receptions
- `temp_f_minus_60` — mild effect on passing (centered so dome games hit baseline naturally)
- `wind_x_pass_attempt_rate` — interaction, QB model only

Features are additive; GLM fitting stays stable. Shrinkage applies to the player-specific intercept; weather coefficients pool across all players. The `use_weather` flag is what the ablation grid (H2) toggles — no duplicated model classes.

**Test:** `tests/test_model_weather.py` — train QB on 2018–2024 with/without weather; assert AIC delta is within tolerance; deterministic seed.

**New file:** `scripts/train_loop.py` — walk-forward harness:
```
for train_end in [2018, 2019, ..., 2024]:
    holdout = train_end + 1
    for config in grid:
        model = fit(seasons=2018..train_end, **config)
        metrics = evaluate_on(holdout, model)
        write_row(train_end, config, metrics)
    narrate_season(train_end)   # Qwen 1.7B, template-fill
    brain_append(train_end)
```
Deterministic stopping per season: loop stops when `holdout_log_loss` improvement `< 0.001` across the last 3 configs tried, **or** when the grid is exhausted — whichever comes first. No LLM in the stop criterion.

Outputs per season:
- `docs/training/season_<YYYY>_results.csv` — one row per (config, position, stat) with log-loss, Brier, calibration slope/intercept, feature-ablation flags, `k`, L1 alpha.
- `docs/training/reliability_<YYYY>_<position>_<stat>.png` — reliability diagram.

### H2. Ablation grid + L1 regularization path

The "variable weighting" and "leave variables out" part of the idea, done rigorously.

**Grid dimensions** (per run):
- `use_weather ∈ {True, False}`
- `use_opponent_epa ∈ {True, False}` (opponent defensive EPA, already available in nflverse)
- `use_rest_days ∈ {True, False}`
- `use_home_away ∈ {True, False}`
- `k ∈ {2, 4, 6, 8, 12, 16}` — shrinkage constant
- `l1_alpha ∈ {0.0, 0.001, 0.01, 0.1}` — L1 regularization; `0.0` means plain GLM

Full grid = `2^4 × 6 × 4 = 384` configs per season × 7 walk-forward steps = ~2700 fits. Each GLM fits in <1 second on CPU; total ~45 minutes wall-time.

**L1 regularization** replaces hand-tuned "variable weighting." At nonzero `l1_alpha`, coefficients on useless features collapse to zero automatically — this *is* the principled way to answer "which variables should we keep." Ablation flags remain for feature categories you want to force off regardless (e.g., "does weather help on 2019 specifically?").

**Modify:** `models/qb_model.py`, `models/rb_model.py`, `models/wr_te_model.py` — accept `l1_alpha` parameter; when nonzero, fit via `statsmodels.GLM.fit_regularized(alpha=l1_alpha, L1_wt=1.0)` instead of plain `fit()`.

**Test:** `tests/test_l1_path.py` — fit a QB model across the alpha grid on 2018–2019; assert the number of nonzero coefficients is monotonically non-increasing as alpha grows.

### H3. Per-season Qwen 1.7B narration (template fill only)

**New file:** `llm/templates/season_summary.j2` — Jinja2 template with rigid slots:
```
# Training Season {{ season }}

**Holdout:** {{ holdout_season }}

## Headline metrics (best config)
- Best k: {{ best_k }}
- L1 alpha: {{ best_l1_alpha }}
- Feature set: {{ feature_flags }}
- Log-loss: {{ log_loss }} (Δ vs naive: {{ log_loss_delta }})
- Brier: {{ brier }}
- Reliability max deviation: {{ max_reliability_dev }}

## Top 3 features by coefficient magnitude
{{ top_3_features_table }}

## Ablation findings
- Weather on vs off: {{ weather_delta }}
- Opponent EPA on vs off: {{ opp_epa_delta }}
- Rest days on vs off: {{ rest_days_delta }}

## Qualitative observations
{{ qwen_freeform_notes }}  <!-- 2-3 sentences MAX, low-stakes commentary -->
```

**New file:** `scripts/narrate_season.py` — loads `season_<YYYY>_results.csv`, fills every slot with deterministic numeric values, then sends only the rendered scaffold + raw numbers to Qwen 1.7B asking for 2–3 sentences filling `{{ qwen_freeform_notes }}`. All statistical facts are pinned by the template; Qwen cannot corrupt them. Max 80 tokens for the freeform slot, enforced by llama.cpp.

Output: markdown written both to `docs/training/season_<YYYY>_summary.md` and appended to the brain at `E:/AI Brain/ClaudeBrain/02 Work and Career/NFLStatsPredictor/training/season_<YYYY>.md`.

**Test:** `tests/test_narrate.py` — feed a canned results CSV; mock the Qwen HTTP call; assert the rendered markdown contains every slot value verbatim and the Qwen freeform section is ≤ 80 tokens.

### H4. Cross-season synthesis

**New file:** `scripts/synthesize_training.py` — runs after the full walk-forward completes (2018→2024 holdout-on-next). Aggregates all seven `season_<YYYY>_results.csv` files, picks the config that's **Pareto-optimal across seasons** (lowest mean holdout log-loss *and* lowest variance across seasons — penalizes configs that win one year and tank another). Renders:
- `docs/training/cross_season_summary.md` — ranking table, headline recommendation, per-feature ablation rollup.
- `docs/training/cross_season_reliability.png` — overlay of reliability diagrams across seasons for the recommended config.

Then one Qwen 1.7B narration pass fills a final `{{ rollup_notes }}` slot (3–4 sentences, 120 tokens max) summarizing what held up year-over-year.

### H5. Human locks in the final config

Review `cross_season_summary.md` + reliability overlay. Pick the `(k, l1_alpha, feature_flags, calibration on/off)` combination. Document the choice and rationale in `docs/ModelingNotes.md`.

**New file:** `eval/calibration_fit.py` — fit isotonic regression per (position, stat) on 2018–2024 predictions vs actuals; apply to the 2025 hold-out-hold-out. Included here (rather than its own phase) because the walk-forward harness already produces the per-season prediction traces it needs.

**Modify:**
- `models/qb_model.py`, `models/rb_model.py`, `models/wr_te_model.py` — lock in final default `k`, `l1_alpha`, feature flags.
- `eval/prop_pricer.py` — optional calibration pass gated on `settings.use_calibration`.
- `api/settings.py` — set final `use_calibration` default based on H4 evidence.

**Test:** `tests/test_calibration.py` — fit on synthetic data with known ground-truth mapping; assert recovery within tolerance.

**Brain checkpoint:** project note capturing the final config, the Pareto rationale from H4, and the headline metric delta vs v0.5.1 baseline. This becomes the durable record of why the model looks the way it does after 2026.
**Git checkpoint:** update `VERSIONS.md` with v0.8c entry; tag `v0.8c`.

---

## Phase I — v0.8d: Wire Weather to Live Surface

Now that the archive path is proven and cached, light up the UI fields left honest-null in Phase B.

### I1. Attach weather + injury to picks

**Modify:** `api/services/replay_service.py` and `evaluation_service.py` — when building pick payloads, left-join the weather archive frame (loaded once at startup via `data.weather.load_archive(seasons)`). Attach `weather: {temp_f, wind_mph, precip_in, indoor} | null` and `injury_status: "Q"|"D"|"O"|null` to each pick.

**Modify:** `api/schemas.py` — add optional `weather` and `injury_status` fields on the Pick schema.

### I2. Weather + injury badges (real data)

**Modify:**
- `desktop/src/components/weather-badge.tsx` — render wind icon + value (red if >15 mph), temp, precip dot, dome badge. Lucide icons.
- `desktop/src/components/injury-pill.tsx` — Q/D/O color-coded pill from `nflverse_loader.load_injuries()`.
- `desktop/src/components/player-card.tsx` — pass real props instead of `null`; "No current feed" / "Status unknown" fallbacks stay as guards.

### I3. Forecast path for in-season (dormant)

Leave `data/weather.py:load_forecast()` implemented but note it only exercises once the season starts. One-line note in `docs/ModelingNotes.md` pointing to where the forecast path activates.

**Git checkpoint:** update `VERSIONS.md` with v0.8d entry; tag `v0.8d`.

---

## Critical Files — Quick Reference

**New:**
- Trading core (full): `api/trading/{types,adapters,risk,ledger,mapper,pricing,audit,secrets,paper_adapter}.py`
- Kalshi (scaffold): `api/trading/kalshi/{__init__,client,adapter,ws,signing}.py`
- API routes: `api/routes/{execution,secrets}.py`
- Services: `api/services/execution_service.py`
- Telemetry: `api/telemetry.py`
- Weather: `data/stadium_coords.py`, `scripts/backfill_weather.py`
- Modeling: `scripts/train_loop.py`, `scripts/narrate_season.py`, `scripts/synthesize_training.py`, `eval/calibration_fit.py`, `llm/templates/season_summary.j2`
- Desktop: `desktop/src/routes/execution-page.tsx`, `desktop/src/components/glossary-tooltip.tsx`
- Tests: `tests/trading/test_*.py`, `tests/test_analyst_stream.py`, `tests/test_stadium_coords.py`, `tests/test_weather_backfill.py`, `tests/test_model_weather.py`, `tests/test_l1_path.py`, `tests/test_narrate.py`, `tests/test_calibration.py`, `desktop/src/**/__tests__/*.test.tsx`, `desktop/tests/a11y.spec.ts`
- Docs: `docs/TradingOps.md`, `docs/ModelingNotes.md`, `docs/calibration/*.png`

**Modified (small edits):**
- `desktop/index.html`, `desktop/README.md` — Vite-template leaks
- `desktop/src-tauri/tauri.conf.json` — CSP
- `api/server.py` — CORS, exception handler, telemetry init, new routers
- `api/routes/analyst.py` — emit `tool_call` events
- `api/schemas.py` — weather/injury on Pick
- `api/services/replay_service.py`, `evaluation_service.py` — attach weather + injury
- `api/settings.py` — risk caps, `use_calibration` flag
- `desktop/src/main.tsx`, `router.tsx`, `App.tsx` — QueryClientProvider, nav, routes
- `desktop/src/routes/dashboard-page.tsx`, `player-detail-page.tsx`, `parlay-builder-page.tsx` — React Query, filters, analyst context
- `desktop/src/components/{analyst-panel,player-card,weather-badge,injury-pill}.tsx` — honest placeholders, starter prompts, wired data
- `desktop/src/lib/api.ts` — envelope unwrap + new endpoints
- `desktop/src/store/app-store.ts` — persisted prefs
- `desktop/package.json`, `vitest.config.ts` — test tooling
- `pyproject.toml` — otel, keyring deps
- `data/weather.py` — real `load_archive` + `load_forecast`
- `data/nflverse_loader.py` — `load_weekly_with_weather`
- `models/qb_model.py`, `rb_model.py`, `wr_te_model.py` — weather features + new default `k`
- `api/trading/mapper.py` — `KalshiMapper` added in F4
- `eval/prop_pricer.py` — optional calibration pass
- `VERSIONS.md` — entries for v0.6a/b/c, v0.7a, v0.7b-scaffold, v0.8a-scaffold, v0.8b/c/d

**Read-only (reused):**
- `eval/replay_pipeline.py`, `eval/calibration_pipeline.py`
- `api/services/{replay_service,evaluation_service,fantasy_service}.py` (read in Phases D–F; modified in Phase I)
- `desktop/src-tauri/src/lib.rs` (sidecar spawn; no changes)

---

## Explicitly Out of Scope

Belongs to v0.9+ (post-season-start activation):
- Polymarket global (CLOB V2) adapter.
- Polymarket US adapter (separate from global; KYC + Ed25519 signing; regulated DCM).
- **Kalshi live activation** — real `demo-api.kalshi.co` calls, real WebSocket listener, real mapper-to-ticker logic. Swap happens inside `api/trading/kalshi/client.py` and `ws.py`; no callers change.
- Real-money execution on any venue.
- Cross-venue arbitrage or market-making strategies.
- Multi-user or remote execution topology.
- Compliance/KYC/geolocation automation.

---

## Verification

Per phase, in order:

**A (v0.6a):** `uv run pytest -q` passes incl. new `test_analyst_stream.py`; `npm run tauri dev` shows no CSP violations; all pages render via React Query (no duplicate requests on re-mount).

**B (v0.6b):** No "Step N" strings on dashboard; filter controls change visible picks live; `null` weather/injury render honestly; analyst shows starter chips + receives `stat`/`line` context; zero axe violations.

**C (v0.6c):** Forced exception returns envelope schema; theme persists across reload; `docs/telemetry/spans-<date>.jsonl` has spans; `cd desktop && npm test` passes.

**D (v0.7a):** `uv run pytest tests/trading -q` passes; no routes or UI changed yet.

**E (v0.7b-scaffold):** Submit 3 picks on Execution page → fills appear; Cancel works; Kill flips all open to `canceled`; paper-mode banner visible on every screenshot; Playwright e2e passes.

**F (v0.8a-scaffold):** `tests/trading/test_kalshi_signing.py` passes (RSA-PSS round-trip with test keypair); `tests/trading/test_secrets.py` passes; UI shows "Kalshi (Demo) — Coming preseason" disabled option with tooltip; no live HTTP calls anywhere.

**G (v0.8b):** `scripts/backfill_weather.py` populates `data/cache/weather_archive.parquet` with one row per outdoor game for 2018–2025; `uv run python -c "from data.weather import load_archive; print(load_archive([2024]).head())"` returns real temps/winds; dome games are flagged `indoor=True` with null numeric fields.

**H (v0.8c):** `scripts/train_loop.py` produces `docs/training/season_<YYYY>_results.csv` for every walk-forward step 2018→2024; reliability diagrams rendered per (season, position, stat); Qwen 1.7B season-summary markdown exists per season both in `docs/training/` and the brain; `cross_season_summary.md` documents final `(k, l1_alpha, feature_flags, calibration)` choice with Pareto rationale and headline deltas vs v0.5.1; `docs/ModelingNotes.md` records the locked config; all tests green.

**I (v0.8d):** A Week-1 outdoor game pick on the dashboard shows real wind/temp/precip; a Week-1 indoor game shows a dome badge; a player with an injury designation from nflverse shows Q/D/O pill; null cases still render "No current feed" / "Status unknown".

---

## Season-Start Activation Checklist (post-v0.8d, not in this plan)

When preseason opens (~August 2026), in-season activation is mechanical:

1. Provision a Kalshi demo account; store credentials via `POST /api/secrets/kalshi`.
2. Replace `NotImplementedError`s in `api/trading/kalshi/client.py` with real HTTP calls.
3. Replace `ws.py`'s stub with a real authenticated WebSocket listener.
4. Implement `KalshiMapper.map_signal` using Kalshi's `get_markets` discovery.
5. Flip the venue selector to enabled; change banner to amber "Kalshi demo — mock funds, real venue".
6. Run `tests/trading/test_kalshi_contract.py` against demo (gated on `KALSHI_DEMO_KEY`).
7. Exercise weather forecast path on Week-1 upcoming games.

No file structure changes. No caller changes. That's the point of shipping the scaffolding now.
