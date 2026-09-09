# Desktop GUI Overhaul — Plan

Branch: `worktree-agent-a9ac212a06ee9d597` (from master @ `1496c9f`).
Sidecar for dev: `uv run uvicorn api.server:app --host 127.0.0.1 --port 8100` (run from `E:\Projects\NFLStatsPredictor` — the worktree has no `cache/`, so a worktree-run cold-downloads nflverse; the main repo has the warm cache and identical committed backend at `1496c9f`).
Dev: `VITE_API_BASE_URL=http://127.0.0.1:8100 npm run dev --prefix desktop` → `http://localhost:5173`.

## 1. What the API actually gives us (verified against a live sidecar)

15 endpoints, all reachable. Key findings that shape the UI:

- **`DistributionSummary` is `{mean, std, dist_type}` only** — no `quantiles`, no `samples` (the task brief's schema note is aspirational). The distribution viz therefore **synthesises** the PDF curve + P10/P50/P90 client-side from `mean`/`std`/`dist_type` (`negative_binomial`, `poisson`, `gamma`, `beta`, `quantile`→lognormal-approx, `normal`). This is an approximation and is labelled as such in the UI.
- **Rich per-stat data (`over`/`under` `SidePrice`, `distribution`, `policy`) comes only from `POST /api/props/evaluate`.** `/api/slate.top_picks` and `/api/replay/summary.picks` are "thin" (`selected_*`, `model_p_*_calibrated`, `market_p_*_no_vig`, `ev_*`, `recommendation`, `confidence`; `distribution`/`over`/`under`/`top_drivers` are null/empty there).
- **`/api/slate` is cold ~30–60 s** (fits models + loads an 18.8k-row replay artifact). Returns 2025-labelled **replay** history, not an upcoming slate. ~30 KB.
- **`/api/replay/summary` is ~17 MB / 18,801 graded picks** — lazy-load + virtualregister only on the Replay route.
- **No schedule or roster endpoint.** The "current-week upcoming slate" cannot be enumerated from the API. Worked around: `desktop/src/data/schedule-2026.json` (272 REG games) + `desktop/src/data/players-2026.json` (400 skill players, 366 on 2026 rosters, with 2025 volume) generated **read-only** from the repo's warm parquet cache. The This Week board maps each pooled player to their real Week-N opponent from that file and drives `/api/props/evaluate` + `/api/fantasy/predict` (`use_future_row=True` is on, so 2026 Week 1 prices correctly — Mahomes ≈ 290 pass yд, informative `P(over)`).
- **`/api/props/evaluate` needs `over_odds`/`under_odds`** — no market lines exist for 2026, so the board sends neutral `-110/-110` and labels the line a **"model line (no market)"**; edge is model prob − no-vig(0.5), EV is vs -110. Honest, not a market edge.
- **Model projections are uncalibrated with a known forward mean-bias** (QB passing_yards ≈ +24 yд/gm, receiving_yards ≈ +4 on 2025 holdout; `docs/season_eve_2026_dryrun.md` §5). Every projection surface carries a standing disclosure; `use_calibration=False`.
- **`llama.cpp` :8080 is down in this environment** → `/api/analyst/stream` emits `{"event":"error", ...}` then `{"event":"complete"}`. Analyst panel is fully wired and handles the offline frame; live token rendering is covered by mocked tests.
- `/api/execution/*` paper stack works: `portfolio` `{cash_balance, realized_pnl, unrealized_pnl, positions[]}` (envelope `{success,data}`), `events?since=` (envelope), `events/stream` SSE (`data: {kind,ts,...}`), `kill` `{killed,reason}`, `paper/submit` → intent-status array, `paper/cancel`.
- `/api/secrets/kalshi` needs `{access_key, private_key_pem, confirm_token}`; the confirm token is printed to the **sidecar log** each boot ("Kalshi secret-vault confirmation token: …"). Settings surfaces that instruction; the client never persists the values.

## 2. Stack (one line each; net dependency reduction)

| Concern | Choice | Why (1 line) |
|---|---|---|
| Router | **TanStack Router** (code-based route tree) | Task/modernization target; full type-safety without adding the file-route Vite plugin + codegen watcher. Removes `react-router-dom`. |
| Server state | **TanStack Query** (kept) | Already in place; pairs with the router; per-row queries let the board stream in. |
| Virtualization | **@tanstack/react-virtual** (added) | Replay Explorer renders 18.8k rows; windowing is the only sane option. |
| Table state | **@tanstack/react-table** (kept) | Already a dep; drives sort/filter on the replay + board tables. |
| API client | **openapi-typescript** (dev) + **openapi-fetch** (~6 kB runtime) | Task mandate: generated types, no hand-maintained response shapes. `npm run generate-api`. |
| Components | **Local shadcn-style primitives on a minimal Radix core** (`dialog`, `tooltip`, `tabs`, `slot`, `label`) | "Fewer Radix packages": drop ~20 unused Radix + `framer-motion`/`embla`/`vaul`/`cmdk`/`input-otp`/`react-resizable-panels`. |
| Toasts | **sonner** (kept) | Small, `aria-live` built in; execution/submit feedback. |
| Dataviz | **hand-built inline-SVG components on `d3-scale` + `d3-shape`** (added; ~12 kB, tree-shaken) | Distribution curve/band, sparkline small-multiples, edge/EV bars are ~40-line SVG; full control of the WCAG text-alternative + data-table toggle; drops Recharts (~500 kB) + `@types/recharts`. Recharts is the documented fallback if this balloons. |
| Styling | **Tailwind v4 + semantic CSS-variable tokens** (kept, tokenised) | Dark-first (Tauri app) with a real working light theme via `:root` / `[data-theme]`; contrast rebuilt to ≥ 4.5:1. |
| Prefs state | **Zustand** (kept) | Theme, density, default min-edge/stats, bet slip. |
| Fonts | **Inter + JetBrains Mono** via Google Fonts (kept) | CSP already allows `fonts.googleapis.com`/`gstatic`; mono numerics suit dense financial tables. |
| a11y lint | **eslint-plugin-jsx-a11y** (added) | Static gate alongside axe/Lighthouse. |

Net: **−~26 deps, +6** (`@tanstack/react-router`, `@tanstack/react-virtual`, `openapi-fetch`, `d3-scale`, `d3-shape`, and dev `openapi-typescript`, `eslint-plugin-jsx-a11y`, `@types/d3-*`).

## 3. Visual direction

Analytical instrument, not a marketing surface — "a to-do list wearing charts" (exception-first: what needs a decision reads first). Dark-first slate/graphite ground; **one** accent (emerald) for interactive affordance and model-positive; semantic red/amber reserved for negative edge / warnings / kill, always paired with a glyph + sign (never colour alone). JetBrains Mono for every number, `tabular-nums`, signed. Density toggle (comfortable 48 px / compact 36 px rows). No hero; the This Week board is the first paint.

## 4. Information architecture

| Route | Purpose | Endpoints surfaced |
|---|---|---|
| `/` **This Week** | The app's real job. 2026 Week-N board: per player·stat → model mean (±bias note), model line, P(over)/P(under), no-vig, edge, EV, confidence, distribution mini, top drivers, injury/weather, fantasy pts. Filters: week, game, team, position, stat, min-edge, search. Table (virtual) ↔ card toggle. Add-to-slip. | `props/evaluate`, `fantasy/predict`, (`health` status dot) |
| `/replay` **Replay Explorer** | 2025 backtest. KPI tiles, 4 baselines, best/worst leaders, stat/week/book breakdowns, interpretation, validation + skipped-rows, top picks/parlays. Full 18,801-pick table (virtual, sort/filter) + parlay rows + replay context. | `slate`, `replay/summary` |
| `/players` + `/players/$playerId` | Search (pool). Detail: game log table, per-stat rolling-form sparkline small-multiples, projection panel (evaluate+fantasy for a chosen upcoming week w/ opponent from schedule), replay-pick history, Analyst launcher. | `players/{id}`, `props/evaluate`, `fantasy/predict`, `analyst/stream` |
| `/parlays` **Parlay Builder** | Build from slip / board / replay picks. Joint prob, decimal odds, EV, same-game & same-team penalty (explained as correlation), mean edge, per-parlay grade when present. | `parlays/build` |
| `/execution` **Execution (Paper)** | Queue (slip + board + replay), Submit / Submit all, cancel, kill switch; portfolio (poll 3 s); audit list (`events?since=`) + live SSE tail (`aria-live` polite); venue selector (Paper active; Kalshi demo disabled → link to Settings with the real reason). | `execution/paper/submit`, `execution/paper/cancel`, `execution/kill`, `execution/portfolio`, `execution/events`, `execution/events/stream` |
| `/settings` | Theme, density, default min-edge/stats, scoring mode; System panel (all `health` fields + live status); Kalshi credentials form (`secrets/kalshi`, confirm-token-from-log instruction, never persisted client-side). | `health`, `secrets/kalshi` |

Analyst is a slide-over (not a route), reachable from `/` rows and `/players/$id`.

### Endpoint → view coverage (target: 15/15)

1 `health`→Settings+status dot · 2 `slate`→Replay · 3 `replay/summary`→Replay · 4 `players/{id}`→Players detail · 5 `props/evaluate`→This Week + Players · 6 `fantasy/predict`→This Week + Players · 7 `parlays/build`→Parlays · 8 `analyst/stream`→Analyst slide-over · 9 `execution/paper/submit`→Execution · 10 `execution/paper/cancel`→Execution · 11 `execution/kill`→Execution · 12 `execution/portfolio`→Execution · 13 `execution/events`→Execution audit list · 14 `execution/events/stream`→Execution live tail · 15 `secrets/kalshi`→Settings.

## 5. Component inventory (new / rebuilt, all under `desktop/src`)

- `lib/api-schema.d.ts` (generated), `lib/api-client.ts` (openapi-fetch + Tauri `invoke('api_base_url')` base-URL resolve, kept intact; browser fallback = `VITE_API_BASE_URL`), `lib/api.ts` (typed endpoint fns + SSE readers), `lib/queries.ts` (query keys/hooks).
- `lib/distribution.ts` — PDF + quantiles per `dist_type` (+ unit tests).
- `lib/format.ts` — `num`, `signed`, `pct`, `odds`, `units`, `n=` guards (never `NaN`/`undefined`/`[object Object]`).
- `lib/schedule.ts` — schedule/pool loaders + "current week" (date-based, default Wk 1).
- `router.tsx` (route tree), `routes/*` (6), `app/` shell: `AppShell`, `SideNav`, `RouteAnnouncer` (focus `h1` + `aria-live`), `SkipLink`, `ThemeProvider`, `ErrorState`, `EmptyState`, `LoadingState`, `SlateProgress` (elapsed + staged copy for the cold `/api/slate`).
- charts: `DistributionChart` (curve + P10/P50/P90 band + line marker + table toggle), `Sparkline`, `SmallMultiples`, `EdgeBar`, `ProbBar`, `CalibrationNote`.
- domain: `ThisWeekBoard` + `PropRow`/`PropCard`, `EdgeIndicator` (colour+arrow+sign), `ConfidencePip`, `InjuryTag`, `WeatherTag`, `DriversList`, `ProjectionPanel`, `FantasyBreakdown` (components + context_factors + boom/bust), `ReplayTable`, `KpiTile`, `BaselineGrid`, `LeaderCard`, `BreakdownList`, `ValidationPanel`, `ParlayBuilder`, `SlipDrawer`, `ExecutionQueue`, `OrderList`, `PortfolioPanel`, `EventTail`, `KillSwitch`, `VenuePicker`, `AnalystPanel`, `PlayerSearch`, `GameLogTable`, `SystemPanel`, `KalshiSecretsForm`, `BiasDisclosure`, `Glossary`.
- `store/app-store.ts` — extend: `density`, `betSlip[]`, `dismissedBiasNote`.

## 6. Iteration plan (wiring + a11y before polish; commit per slice)

- **S1 Foundations** — deps prune/add; `generate-api` + client + typed `api.ts`; tokens/`globals.css` (light+dark, contrast); TanStack Router shell, `RouteAnnouncer`, `SkipLink`, `SideNav`, primitives; `format.ts`, `distribution.ts` (+tests). Green build/lint/test.
- **S2 Replay Explorer** — `/api/slate` + `/api/replay/summary` fully surfaced; virtual 18.8k table; KPI/baseline/leader/breakdown/validation; `SlateProgress`. Loading/empty/error.
- **S3 This Week board** — schedule/pool wiring; per-row evaluate+fantasy (concurrency-capped, cached, streaming rows); `DistributionChart`; filters; slip; `BiasDisclosure`.
- **S4 Players** — search + detail; game log; rolling-form small-multiples; projection panel; replay history.
- **S5 Parlay Builder** — build from slip/board/replay; joint prob / EV / penalties / mean edge.
- **S6 Execution** — queue, submit/all, cancel, kill, portfolio poll, events + SSE tail (`aria-live`), venue picker.
- **S7 Analyst slide-over + Settings** — SSE tokens/tool-calls + offline handling; System panel; Kalshi form.
- **S8 a11y hardening** — axe + Lighthouse per route → ≥ 95 a11y, 0 serious/critical; focus order, landmarks, contrast in dark, chart table-toggles, live regions.
- **S9 Polish** — dataviz refinement, ~900 px responsive, empty/error sweep, number-format sweep, 0 console errors.
- **S10+ Audit loop** — Lighthouse (perf ≥ 85 / a11y ≥ 95 / BP ≥ 95) + axe + console + vitest + lint + build, per route, logged to `GUI_OVERHAUL_LOG.md`, until two consecutive clean full audits.

## 7. Known blockers routed around (carried to the handoff)

- No **schedule/roster** endpoint → embedded `schedule-2026.json` / `players-2026.json` from the warm cache; a `/api/startup/snapshot` or schedule route is the real fix (modernization Phase 6).
- No **market lines** for 2026 → board uses model line + neutral odds; edge/EV are model-vs-fair, not market.
- `DistributionSummary` lacks **quantiles/samples** → client-side synthesis from `mean/std/dist_type`.
- **Calibration off / +24 yд forward bias** → standing disclosure, not hidden.
- **llama.cpp :8080 down here** → Analyst offline-state wired + tested; live tokens not exercised in this environment.
