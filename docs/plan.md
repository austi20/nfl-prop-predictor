# NFL Prop Prediction Desktop App - Implementation Plan

## Context

User built an NBA prop prediction desktop app (code on a different machine) that:
- Pulls player stats from BALLDONTLIE API
- Predicts daily stat lines, compares vs sportsbook props
- Generates confidence ratings and parlay suggestions
- Uses a local Qwen3 1.7B model (llama.cpp server) as an analyst layer that evaluates statistical integrity, controls stat display, and weighs player/team/situational context

Goal: replicate the architecture for NFL. Constraints:
- NFL season is in the offseason right now (April 2026) - no live games for weeks
- Must train/backtest on historical data before Week 1 (Sept 2026)
- Favor free APIs; only use paid if decisively better on statistical integrity or data depth

## Feasibility Summary

Porting to NFL is moderately harder than NBA for three reasons worth noting up front:
1. **Sample size.** NFL = 17 games/player/year vs NBA 82. Bayesian shrinkage and multi-season priors matter much more.
2. **Weather + game script.** NFL props are heavily dependent on wind/precipitation and whether the team is leading/trailing (pass/run balance flips). Needs extra feature engineering NBA did not require.
3. **Position heterogeneity.** QB/RB/WR/TE/K/DEF all need separate models. NBA had one model per stat across all players.

The good news: the free NFL data ecosystem (nflverse) is *better* than BallDontLie for modeling - play-by-play back to 1999 with EPA/CPOE pre-computed.

## Data Sources

### Primary: nflverse (free, gold standard)
- **nfl_data_py** (Python) - wraps nflfastR data. Install via pip.
  - `import_pbp_data()` - play-by-play 1999-present (EPA, CPOE, WPA pre-computed)
  - `import_weekly_data()` - player weekly box scores
  - `import_seasonal_data()` - season aggregates
  - `import_rosters()`, `import_schedules()`, `import_team_desc()`
  - `import_ngs_data()` - Next Gen Stats (air yards, separation, rush yards over expected)
  - `import_injuries()` - weekly injury reports
  - `import_snap_counts()` - critical for opportunity-based props
  - `import_qbr()`, `import_combine_data()`, `import_draft_picks()`
- Repo: https://github.com/nflverse/nfl_data_py
- Alternative port: **nflreadpy** (newer, actively maintained replacement).
- Updated nightly during season. No API key, no rate limit, pulls from R2/GitHub releases.

### Secondary: BALLDONTLIE NFL (free tier)
- Has NFL endpoints (teams, players, games, stats, standings, injuries, betting odds).
- Useful for live game-day data and as redundancy against nflverse lag.
- Keep it for live mode only; do not train on it (nflverse is deeper).

### Odds (player props)
- **The Odds API** (the-odds-api.com) - free tier 500 req/month, NFL player props across DraftKings/FanDuel/BetMGM/Caesars etc. Paid tiers cheap ($30/mo = 20k req).
- BALLDONTLIE also exposes betting odds on its free tier. Use as fallback/cross-check.
- Paid-but-worth-considering: OddsJam / OpticOdds only if we need sub-second alt-market coverage. Overkill for a desktop app.

### Weather
- **Open-Meteo** (free, no key) - historical + forecast by lat/lon. Stadium coordinates are static.
- Indoor/dome flag: hard-code from `team_desc` roof type.

### Recommendation
Train + backtest: **nfl_data_py only**. Live/inference add **The Odds API** (props) + **Open-Meteo** (weather) + **BALLDONTLIE** (redundancy). Total free-tier cost: $0 for MVP.

## Architecture

```
+------------------------------------------------+
|  Desktop UI (Tauri 2.0 + React + shadcn/ui)    |
|     <-- localhost REST -->                     |
|  FastAPI sidecar (bundled Python .exe)         |
+------------------------------------------------+
|  Prediction Service                            |
|   - per-position models (QB/RB/WR/TE/K/DEF)    |
|   - per-stat heads (pass yds, rush yds, rec,   |
|     rec yds, TDs, INTs, etc.)                  |
|   - Bayesian shrinkage (small sample)          |
|   - Game-script simulator (500k Monte Carlo)    |
+------------------------------------------------+
|  Prop Evaluator                                |
|   - joins model distribution vs book line      |
|   - fair-price / edge / confidence             |
|   - correlation-aware parlay builder           |
+------------------------------------------------+
|  LLM Analyst (Qwen3 1.7B via llama.cpp)        |
|   - same interface as NBA app                  |
|   - tool-calls into stats/prediction service   |
|   - narrative on injuries, weather, script     |
+------------------------------------------------+
|  Data Layer                                    |
|   - nflverse parquet cache (local)             |
|   - Odds API poll (live)                       |
|   - Open-Meteo (weather)                       |
+------------------------------------------------+
```

## Feature Set (per-stat model inputs)

Reuse from NBA: rolling averages, usage rate, opponent-adjusted stats, home/away, rest, recent form.

NFL-specific additions:
- **Snap share** + **route participation** (WR/TE/RB)
- **Target share** + **air yards share** + **aDOT** (WR/TE)
- **Red zone usage** (goal-line carries, RZ targets)
- **Pace of play** (plays/game, seconds/play)
- **Opponent defensive DVOA / EPA allowed by position**
- **Game script projection** (Vegas spread + total -> implied pass/run split)
- **Weather**: wind > 15 mph, precip, temp, dome flag
- **Offensive line health** (pressure rate allowed, run block win rate)
- **Injury designations** (Q/D/O) on player AND position group around them
- **Coaching tendencies** (pass rate over expected from pbp)

## Modeling Approach

Position-specific regression + distributional output (we need distributions, not point estimates, to price props correctly):

- **QB passing yards/TDs/INTs/completions**: Negative binomial or Tweedie GLM, features above.
- **RB rush yards/attempts/TDs**: Tweedie (zero-inflated); rush attempts gated on game-script sim.
- **WR/TE receptions/rec yards/rec TDs**: Poisson for receptions, Gamma/log-normal for yards, conditional on target sim.
- **Kicker FG/points**: Poisson, conditional on drive count + red-zone stall rate.

All wrapped in a 500k-sim Monte Carlo at the game level so correlated props (QB pass yds + his WR1 rec yds) share the same simulated paths - this is what enables correlation-aware parlays.

Training: 1999-2025 play-by-play, walk-forward CV by season. Replay paper-trade edges against local historical prop files first, with live-season Odds API ingestion reserved for later live execution.

Shrinkage: Empirical Bayes per position toward position-group prior - this handles the small-sample NFL problem.

## LLM Analyst Layer

Keep the exact same llama.cpp-server + Qwen3-1.7B pattern. Only the tool surface changes:

- `get_player_projection(player_id, stat)` -> returns mean, sd, quantiles
- `get_historical_vs_defense(player_id, opp_team)`
- `get_weather(game_id)`
- `get_injury_context(team_id)`
- `get_recent_news(player_id)` - optional, needs news source (RotoWire free RSS, or skip)
- `evaluate_prop(player_id, stat, book, line, over_under)` -> model fair price + edge

Analyst system prompt instructs it to flag statistical integrity issues (tiny sample, stale data, injury mid-week) before recommending. Same pattern as NBA app.

## Offseason Plan (now -> Sept 2026 kickoff)

Use dead-time productively:

### Step 1 - Ingest + cache nflverse (1999-2025). ~2-5 GB parquet. One-time.

> Files: `data/nflverse_loader.py`, `cache/` directory
>
> Done when: all nfl_data_py imports succeed, parquet files on disk, smoke tests pass.

---
### CHECKPOINT v0.1 - Push to GitHub
**Tag:** `v0.1`
**Push when:** nflverse parquet cache complete and smoke-tested. All `data/nflverse_loader.py` imports verified (row counts, expected columns). Update `VERSIONS.md` before pushing.

---

### Step 2 - Build + backtest models on 2015-2024, hold out 2025 as final test set.

> Files: `models/qb.py`, `models/rb.py`, `models/wr_te.py`, `models/game_sim.py`
>
> Done when: walk-forward CV complete across all 4 position groups, metrics logged.

---
### CHECKPOINT v0.2 - Push to GitHub
**Tag:** `v0.2`
**Push when:** All position models trained and walk-forward CV metrics recorded. `models/` directory complete. Update `VERSIONS.md` before pushing.

---

### Step 3 - Fit confidence calibration (Platt/isotonic) on 2025 closing lines.

> Files: `eval/prop_pricer.py`
>
> Done when: reliability diagram is near-diagonal on 2025 hold-out, calibration coefficients saved.

---
### CHECKPOINT v0.3 - Push to GitHub
**Tag:** `v0.3`
**Push when:** Calibration fitted and validated on 2025 hold-out. Reliability diagram saved to `docs/`. Update `VERSIONS.md` before pushing.

---

### Step 4 - Harden local historical props replay for 2024-2025 paper-trading.

> Files: `eval/replay_pipeline.py`, `eval/prop_pricer.py`, `eval/parlay_builder.py`, `docs/Step4Plan.md`
>
> Done when: local historical props replay runs end-to-end for 2024-2025 with stable artifacts under `docs/`, and the selected replay policy reaches non-negative to positive ROI after vig on the tracked evaluation set.

---
### CHECKPOINT v0.4 - Push to GitHub
**Tag:** `v0.4`
**Push when:** Local replay pipeline contract is stable, 2024-2025 replay artifacts are documented in `docs/`, and Step 4 closeout language is reflected in `VERSIONS.md` before pushing.

---

### Step 5 - Build Tauri/React/shadcn desktop UI from scratch + wire FastAPI sidecar + LLM analyst panel. Split into 5a/5b/5c for incremental checkpoints.

**Stack:** Tauri 2.0 + React 18 (Vite) + shadcn/ui + Tailwind CSS. FastAPI sidecar bundled via PyInstaller provides localhost REST bridge to Python models. Windows `.msi` target. All tooling MIT/Apache — $0 licensing cost.

**Layout:**
- `api/` — FastAPI sidecar (`server.py`, `routes/`, `schemas.py`)
- `desktop/src-tauri/` — Rust shell + `tauri.conf.json` + sidecar binding
- `desktop/src/` — React app (`routes/`, `components/`, `lib/api.ts`, `styles/globals.css`, Zustand stores)
- `llm/tools_nfl.py`, `data/weather.py` (unchanged ownership)

**Design system (locked in 5a):** Dark-first slate palette, emerald/rose semantic accents, Inter + JetBrains Mono (tabular numerals), 12/14/16px density scale, 150ms motion, Lucide icons. Custom components: `<EdgeBadge>`, `<ConfidenceBar>`, `<DistChart>`, `<PlayerCard>`, `<InjuryPill>`, `<WeatherBadge>`.

---
### CHECKPOINT v0.5a - Push to GitHub
**Tag:** `v0.5a`
**Push when:** Tauri shell boots, FastAPI sidecar auto-starts on ephemeral localhost port, one live end-to-end page (weekly slate fetched from `/api/slate`) renders real data, design tokens in `globals.css` locked, `.msi` build succeeds. Update `VERSIONS.md` before pushing.

---
### CHECKPOINT v0.5b - Push to GitHub
**Tag:** `v0.5b`
**Push when:** Slate view, player detail (distribution chart + prop edge table), and parlay builder pages all wired to real Python model output. Visual regression snapshots captured at 1440x900 and 1920x1080. Update `VERSIONS.md` before pushing.

---
### CHECKPOINT v0.5c - Push to GitHub
**Tag:** `v0.5c`
**Push when:** LLM analyst panel streams Qwen3 tokens via SSE with cancellation, weather/injury visualizations shipped, accessibility pass complete (axe-core clean, full keyboard nav), signed-or-unsigned `.msi` under 50 MB installs cleanly on a host with no Python/Node. Update `VERSIONS.md` before pushing.

---

### Step 6 - Preseason (Aug 2026) - add live odds ingestion and dry-run the preseason pipeline.

> Done when: The Odds API live feed is normalized into the Step 4 replay shape, the pipeline runs live on a preseason slate without errors, and stale-data detection works.

---
### CHECKPOINT v0.6 - Push to GitHub
**Tag:** `v0.6`
**Push when:** Preseason dry-run complete. Any bugs from live data caught and fixed. Update `VERSIONS.md` before pushing.

---

### Step 7 - Week 1 (Sept 2026) - go live.

> Done when: live slate produces dashboard + LLM report + parlay suggestions with no manual intervention.

---
### CHECKPOINT v0.7 - Push to GitHub
**Tag:** `v0.7`
**Push when:** Week 1 live run complete. Final go-live validation passed. Update `VERSIONS.md` before pushing.

---

## Critical Files to Create (once code is back on this machine)

- `data/nflverse_loader.py` - wraps nfl_data_py imports, parquet cache
- `data/odds_client.py` - The Odds API wrapper
- `data/weather.py` - Open-Meteo wrapper
- `models/qb.py`, `models/rb.py`, `models/wr_te.py`, `models/kicker.py`
- `models/game_sim.py` - Monte Carlo engine, game-script simulator
- `eval/prop_pricer.py` - distribution -> fair price -> edge
- `eval/parlay_builder.py` - correlation-aware parlay builder
- `llm/tools_nfl.py` - tool definitions exposed to Qwen3 analyst
- `api/server.py`, `api/routes/`, `api/schemas.py` - FastAPI sidecar bridging desktop UI to Python services
- `desktop/src-tauri/` - Tauri 2.0 shell (Rust), `tauri.conf.json`, sidecar binding to PyInstaller `.exe`
- `desktop/src/` - React app (routes, components, `lib/api.ts`, Tailwind design tokens, Zustand stores)

## Verification

- **Unit**: each nfl_data_py import has a smoke test (row count > 0, expected columns present).
- **Backtest**: on held-out 2025 season, model-implied probabilities should beat closing line > 50% on high-confidence picks (edge > 5%); ROI positive after -110 vig.
- **Calibration**: reliability diagram on predicted over/under probabilities - near diagonal.
- **Integration**: end-to-end run on a 2025 Sunday slate produces a dashboard matching UI mockup; LLM analyst narrative references the correct injuries/weather.
- **Live smoke**: preseason week, compare live Odds API lines vs cached BALLDONTLIE odds - detect stale data.

## Resolved Scope Decisions

- **Stack: Python end-to-end** via `nfl_data_py` (with `nflreadpy` as newer alternative). Rationale: faster cache loads via parquet, pandas/numpy/scikit-learn/llama-cpp-python all in one language, matches llama.cpp server integration. Nflverse parity between R and Python is ~95%; missing bits (if any) are advanced model columns that we recompute ourselves from raw pbp anyway.
- **Paper-trading: in scope.** Replay 2024 and 2025 seasons from local historical props files as the calibration and confidence gate before live mode; The Odds API stays reserved for live-season odds ingestion.
- **Position scope: QB/RB/WR/TE only.** Kicker and team DEF deferred post-MVP.
- **Desktop UI stack: Tauri 2.0 + React 18 + shadcn/ui + Tailwind CSS.** FastAPI sidecar (bundled via PyInstaller) provides the Python bridge over localhost REST. Windows `.msi` is the v1.0 target (macOS/Linux deferred). All tooling MIT/Apache — $0 licensing cost. Rationale: native webview keeps installer small (10-40 MB vs Electron's 120-200 MB), shadcn gives copy-paste ownership of components with no vendor lock-in, sidecar pattern mirrors the existing llama.cpp sidecar so architecture stays consistent.

## Still Open (answer before implementation)

- Did the NBA app use The Odds API or a different odds source? If different, does that source cover NFL props? (Determines whether odds client is reusable.)

## Sources

- [nfl_data_py](https://github.com/nflverse/nfl_data_py)
- [nflfastR](https://nflfastr.com/)
- [nflverse org](https://github.com/nflverse)
- [BALLDONTLIE API](https://www.balldontlie.io/)
- [The Odds API - NFL](https://the-odds-api.com/sports-odds-data/nfl-odds.html)
- [Open-Meteo](https://open-meteo.com/)
