# Plan: Season-Prep — Inference Fidelity, Training, Pricing, Realistic Paper

## Current Implementation Sequence (2026-04-27)

The post-G.5 sequence now proceeds as **Cleanup -> Pricing -> Execution -> UI -> Training** and is logged in `VERSIONS.md` as:

- `v0.8d-preflight`: stable weather schema, disjoint train/holdout guards, SSE cursor fix, weather availability metadata
- `v0.8e-pricing`: no-vig utility, `PropDecision`, EV selection, no-bet handling
- `v0.8f-execution`: side-aware ledger, realistic paper adapter, exposure risk engine
- `v0.8g-ui`: weather/injury payloads and decision drawer
- `v0.9a-training`: synthetic-surrogate odds loader and future-row ablation hooks

The detailed older phase notes below remain useful background, but the current code follows the version order above.

## Status (as of v0.8b-fgfp-prep, 2026-04-24)

Phases A–F are complete and logged in VERSIONS.md. The workstation is hardened (v0.6a–c), trading domain is live (v0.7a), paper trading + Kalshi scaffold are shipped (v0.7b-scaffold, v0.8a-scaffold).

A 2026-04-24 deep review (`Deep review of the NFL prop predictor repository.pdf`) plus a code-verified Explore audit surfaced five structural gaps the prior plan didn't address. The G/H/I sequence is preserved; three new phases (**G.5**, **J**, **K**) are inserted, and Phase H scope is expanded.

Verified gaps:
- **Future-game inference row.** `predict()` in `models/qb.py:200-229`, `rb.py:176-210`, `wr_te.py:187-240` accepts `opp_team` but never rebuilds features for it; predictions use the latest historical row. Without fixing this, Phase H training improvements are stranded. → **Phase G.5 (FGFP)**.
- **Stat-specific distributions.** Predictive std at `qb.py:248`, `rb.py:228`, `wr_te.py:235` is `prior_std * (shrunk_mean / prior_mean)`, not residual-based; QB TDs/INTs use Gamma instead of count-aware models; tails are not validated. → **Phase H expansions H1.5 / H2.5**.
- **Calibration disjointness.** `eval/calibration_pipeline.py:154-189` and `replay_pipeline.py:278-286` accept `train_years` and `holdout_years` with no assertion they are disjoint. → **Phase H expansion H4.5**.
- **No-vig pricing & EV selection.** `eval/prop_pricer.py:252-284` calibrates over/under dependently but `build_paper_trade_picks` (line 334) ranks on raw probability edge; no `no_vig` utility exists in `eval/`. → **Phase J**.
- **Side-aware ledger & realistic fills.** `OrderEvent` has no `side` (`api/trading/types.py:54-61`); `InMemoryPortfolioLedger._apply_fill` (`ledger.py:58-77`) is side-agnostic; `FakePaperAdapter` fills instantly at limit. → **Phase K**.

Remaining (in execution order):
- **Phase G (v0.8b)** — Open-Meteo Archive weather backfill 2018–2025 + `load_weekly_with_weather` (UNCHANGED)
- **Phase G.5 (v0.8b-fgfp)** — Future-Game Feature Pipeline (NEW)
- **Phase H (v0.8c)** — Walk-forward training + stat-specific distributions + L1 + calibration disjointness (EXPANDED)
- **Phase J (v0.8d-pricing)** — No-vig pricing + decision object + EV-based selection (NEW)
- **Phase I (v0.8d)** — Wire weather/injury/decision drawer to UI (LIGHT EXPANSION)
- **Phase K (v0.8e)** — Realistic paper execution + side-aware ledger (NEW)
- **Season-start (v0.8f)** — Kalshi activation + timestamped quote capture (existing checklist + quote capture)

Polymarket (global V2 + US), historical-props warehouse backfill, real-money execution, and an empirical correlated-parlay model remain **out of scope**, gated behind v0.9 after one paper-trading season.

---

## Phase G — v0.8b: Historical Weather Backfill

Open-Meteo's Archive API (ERA5 reanalysis) has hourly data from 1940 to ~5 days ago, free, no key. Same JSON shape as their forecast API. This phase backfills every NFL game 2018–2025 with actual kickoff-hour weather so models can train on it and replays use faithful conditions.

### G1. Stadium coordinate table

**New file:** `data/stadium_coords.py` — hand-maintained dict keyed by team abbreviation (and legacy codes where franchises relocated: OAK→LV, SD→LAC, STL→LAR). Uses a frozen `Stadium` dataclass:

```python
@dataclass(frozen=True)
class Stadium:
    lat: float; lon: float; altitude_ft: int
    is_fixed_dome: bool; is_retractable: bool; tz: str  # IANA

STADIUMS: dict[str, Stadium] = { ... }  # 32 current + OAK/SD/STL legacy keys
FIXED_DOME_TEAMS  = frozenset(t for t, s in STADIUMS.items() if s.is_fixed_dome)
RETRACTABLE_TEAMS = frozenset(t for t, s in STADIUMS.items() if s.is_retractable)

def is_indoor(team: str) -> bool:
    s = STADIUMS[team]
    return s.is_fixed_dome or s.is_retractable
```

`DOME_TEAMS` in `data/nflverse_loader.py:26-37` mixes fixed domes and retractables in one frozenset. Keep that alias untouched for back-compat; `stadium_coords.py` is the authoritative split. SoFi (LAR/LAC) is treated as outdoor for weather purposes, matching the existing convention. Treat retractables as indoor for weather-skip — roof decisions on game day are not available in nflverse schedules, so the conservative choice avoids phantom outdoor weather for retractable venues.

**Test:** `tests/test_stadium_coords.py` — every team in `nflverse_loader.load_schedules(2018..2025).home_team.unique()` has an entry; all tz strings pass `zoneinfo.ZoneInfo(tz)` without error; `is_indoor` returns True for known fixed domes and retractables, False for known open-air teams.

**Status:** ✅ shipped (35 entries, 22 tests passing).

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
- Unit conversions on ingest: `temperature_2m` (°C) → `temp_f` (°F); `wind_speed_10m` (km/h) → `wind_mph` (mph); `precipitation` (mm) → `precip_in` (inches).
- Error handling: retry 3× with exponential backoff on HTTP 5xx; on 429/403 log the game_id and row count and stop cleanly — never silently skip rows.
- Cache output at `cache/weather_archive.parquet` (repo-root `cache/` dir, matching `data/nflverse_loader.py` convention) with columns: `game_id, season, week, home_team, kickoff_utc, temp_f, wind_mph, wind_dir_deg, precip_in, weather_code, indoor`.
- Idempotent: read existing parquet on startup, skip any `game_id` already present.

**CLI:**
```
uv run python scripts/backfill_weather.py --seasons 2018,2019,2020,2021,2022,2023,2024,2025
```

**Test:** `tests/test_weather_backfill.py` — use `responses` or `pytest-httpx` to mock Open-Meteo; assertions:
- Indoor game → `indoor=True`, zero HTTP calls (assert via mock call count)
- Outdoor game → all 5 weather columns populated with correct units
- Idempotency: second call with existing parquet makes zero HTTP calls

### G3. Weather loader integration

**Modify:** `data/weather.py` (currently a 2-line stub) —
- `load_archive(seasons: list[int]) -> pd.DataFrame` reads `cache/weather_archive.parquet`, filters by season.
- `load_forecast(game_id: str) -> dict | None` hits the Open-Meteo Forecast API for upcoming games; gated on `settings.use_live_forecast` — out-of-season or flag-off returns `None`.
- Both paths share the same output schema (`temp_f, wind_mph, wind_dir_deg, precip_in, weather_code, indoor`) so callers are path-agnostic.

**Modify:** `data/nflverse_loader.py` — add `load_weekly_with_weather(years: list[int], force_refresh: bool = False) -> pd.DataFrame` that left-joins the weekly player-stats frame against `weather.load_archive(years)` by `game_id`. Non-outdoor games have `indoor=True` and null numeric weather columns; models' existing `fillna(0.0)` in `_build_features` handles nulls naturally — no additional coalescing needed. This is the frame Phase H training consumes.

**Brain checkpoint:** project note on weather-backfill cache location and schema so future replays pick it up automatically.
**Git checkpoint:** update `VERSIONS.md` with v0.8b entry; tag `v0.8b`.

---

## Phase G.5 — v0.8b-fgfp: Future-Game Feature Pipeline (NEW)

The single highest-leverage fix in the entire offseason. Without it, every feature-engineering improvement Phase H discovers is stranded behind a `predict()` that grabs the latest historical row and ignores the upcoming opponent.

### G.5-1. Future-row builder

**New file:** `data/upcoming.py` — `build_upcoming_row(player_id: str, season: int, week: int, *, force_refresh: bool = False) -> dict` returns a single-row feature dict for an unplayed game by joining:
- **Schedule** (`nflverse_loader.load_schedules`): `game_id`, `home_team`, `away_team`, `is_home`, `kickoff_utc`, `rest_days` (from prior week).
- **Injuries** (`nflverse_loader.load_injuries`): player's own `report_status` for `(season, week)`; key teammate statuses via roster join (QB out shifts WR/RB usage; primary RB out shifts backup carries; primary WR out shifts secondary target share).
- **Snap-share / route-share trend** (`nflverse_loader.load_snap_counts`): last-4-game offensive snap %, route-participation %, red-zone snap %.
- **Opponent defensive context**: rolling 4-game defensive EPA per play and per route from `load_pbp` (already used in training rows — extract into a shared helper `data/team_context.py::rolling_def_epa`).
- **Weather**: `data.weather.load_forecast(game_id)` if `settings.use_live_forecast`, else `data.weather.load_archive([season])` if game is in the past, else null + `indoor` flag.
- **Game environment**: implied team total derived from spread/total (when available; null otherwise — the field exists for later when market data lands).

Returns a dict whose keys are a strict superset of the columns `_build_features` produces from a historical row, so it can be fed directly into `predict()`.

### G.5-2. Refactor `predict()` to accept future rows

**Modify:** `models/qb.py`, `models/rb.py`, `models/wr_te.py`:
- `predict()` gains a `future_row: dict | None = None` kwarg.
- When `future_row` is supplied, build the feature vector from it directly via a new private `_features_from_dict(row)` helper.
- When `future_row` is None, fall back to current behavior (latest historical row) — back-compat for existing callers during migration.
- The deprecated `opp_team: str` arg is kept for one release with a `DeprecationWarning` when used without `future_row`.

**Modify:** `eval/replay_pipeline.py`:
- For each historical week being scored, call `build_upcoming_row(..., force_refresh=False)` and pass to `predict(future_row=row)`. Use `data.weather.load_archive` (not forecast) so replays use ERA5 truth.
- Holdout: `tests/test_replay_pipeline.py` regression — replay output for 2024 should not change beyond floating-point tolerance versus pre-FGFP results when weather is held off, because the same opp_team / venue context that was implicit in the latest-row hack is now made explicit. Document any meaningful delta in `docs/ModelingNotes.md`.

### G.5-3. Tests

**New file:** `tests/test_upcoming.py`:
- Same player vs. weak vs. strong defense produces materially different `feature_vec` and resulting `mean`.
- Indoor vs. outdoor venue produces different weather fields (null vs. populated).
- Teammate-injury swap (primary RB out) shifts backup snap-share trend in the row.

**New file:** `tests/test_predict_with_future_row.py`:
- `predict(player_id="X", future_row=build_upcoming_row("X", 2024, 5))` against opp BUF vs. opp MIA produces visibly different distributions.
- Without `future_row`, falls back to current behavior (regression locked).

**Brain checkpoint:** project note on `data/upcoming.py` API and the deprecation path for `opp_team`.
**Git checkpoint:** update `VERSIONS.md` with v0.8b-fgfp entry; tag `v0.8b-fgfp`.

---

## Phase H — v0.8c: Walk-Forward Training Loop + Calibration

Per-season walk-forward training driven by a **deterministic harness**, not the LLM. Qwen3 1.7B's role is narration only: structured template-fill into brain notes after each season completes. This phase focuses on **statistical accuracy**, not prop calculations.

**Why walk-forward:** training on year N → holdout-testing on N+1 → advancing is the correct methodology for time-series models. Prevents leakage that plain k-fold CV allows.

**Why deterministic loop, not LLM-driven:** 1.7B cannot reliably judge statistical quality; LLM-iterated tuning leaks the holdout into training via multiple-comparisons. Loop stops on numeric criteria. LLM writes the notes, never decides.

### H1. Statsmodels migration + weather features (flag-guarded)

**Note on filenames:** actual model files are `models/qb.py`, `models/rb.py`, `models/wr_te.py` (not `qb_model.py` etc.). All references below use the real names.

**Note on GLM backend:** current models use sklearn `GammaRegressor`. Phase H requires AIC introspection (for H3 narration), L1 regularization (H2), and family flexibility (H1.5). Statsmodels `GLM.fit_regularized` provides all three; sklearn does not. Migration plan: switch all three models to `statsmodels.formula.api` Gamma GLM at H1 start. Default behavior (l1_alpha=0.0, no weather, legacy family) must produce identical predictions to within floating-point tolerance — verify this before adding weather features. Mixing backends is not acceptable.

**Modify:** `models/qb.py`, `models/rb.py`, `models/wr_te.py` — `_build_features(df, *, use_weather: bool = True)` adds (for outdoor games only; zero for indoor/null):
- `wind_mph` — affects passing_yards, passing_tds most
- `precip_in_kickoff_hour` — affects completions, receptions
- `temp_f_minus_60` — mild effect on passing (centered so dome games hit baseline at 0)
- `wind_x_pass_attempt_rate` — interaction term, QB model only

Features are additive; GLM fitting stays stable. Shrinkage applies to the player-specific intercept; weather coefficients pool across all players. The `use_weather` flag is what the ablation grid (H2) toggles — no duplicated model classes.

**Test:** `tests/test_model_weather.py` — train QB on 2018–2024 with/without weather; assert AIC delta is within tolerance; statsmodels migration produces same predictions as old sklearn baseline to 1e-2; deterministic seed.

### H1.5. Stat-specific distribution architecture (NEW)

Replaces one-regressor-per-stat with a small family of stat-aware models. Adds `dist_family` as a new ablation grid axis.

**Count stats** (passing TDs, INTs, completions, attempts, carries, receptions, rec TDs, rush TDs):
- Default to negative binomial via `statsmodels.GLM(family=NegativeBinomial())`.
- Fall back to Poisson when fitted dispersion ≈ 1 (within ±0.1).
- Use a hurdle / zero-inflated variant only if observed zero mass exceeds Poisson expectation by >20%.

**Yardage stats** (passing yards, rushing yards, receiving yards):
- Keep the Gamma/Tweedie mean estimator from H1 for backward comparison.
- Add a quantile-regression companion (`statsmodels.QuantReg`) at q ∈ {0.1, 0.25, 0.5, 0.75, 0.9}.
- The shared `StatDistribution` gains an empirical-quantile lookup branch so callers can ask for `P(X > line)` from quantiles instead of a Gamma tail with hand-scaled std.

**Decomposition models** (high-leverage stats only):
- Receptions = targets × catch_rate (NegBin × Beta).
- Rushing yards = carries × ypc (NegBin × Gamma).
- Passing yards = attempts × ypa (NegBin × Gamma).
- Compose joint distribution by Monte Carlo (1000 samples) for tail probabilities.

**Grid axis added:** `dist_family ∈ {legacy, count_aware, decomposed}`. Phase H4's Pareto selection picks one per (position, stat) — the family that wins might differ across stats, and that's fine.

**Test:** `tests/test_dist_families.py` — count-aware path produces non-zero probability for `P(TD ≥ 0)` exactly (Poisson/NegBin reach zero); decomposed receptions match a hand-computed example.

### H2. Ablation grid + L1 regularization path

The "variable weighting" and "leave variables out" part of the idea, done rigorously.

**Grid dimensions** (per run):
- `use_weather ∈ {True, False}`
- `use_opponent_epa ∈ {True, False}` (opponent defensive EPA, already available in nflverse)
- `use_rest_days ∈ {True, False}`
- `use_home_away ∈ {True, False}`
- `dist_family ∈ {legacy, count_aware, decomposed}` (new from H1.5)
- `k ∈ {2, 4, 6, 8, 12, 16}` — shrinkage constant
- `l1_alpha ∈ {0.0, 0.001, 0.01, 0.1}` — L1 regularization; `0.0` means plain GLM

Full grid = `2^4 × 3 × 6 × 4 = 1152` configs per season × 7 walk-forward steps = ~8000 fits. Each GLM fits in <1 second on CPU; total ~2.5 hours wall-time — still acceptable, especially overnight.

**L1 regularization** replaces hand-tuned "variable weighting." At nonzero `l1_alpha`, coefficients on useless features collapse to zero automatically — this *is* the principled way to answer "which variables should we keep." Ablation flags remain for feature categories you want to force off regardless (e.g., "does weather help on 2019 specifically?").

**Modify:** `models/qb.py`, `models/rb.py`, `models/wr_te.py` — accept `l1_alpha` parameter; when nonzero, fit via `statsmodels.GLM.fit_regularized(alpha=l1_alpha, L1_wt=1.0)` instead of plain `fit()`. (Handled naturally once H1's statsmodels migration is in place.)

**Test:** `tests/test_l1_path.py` — fit a QB model across the alpha grid on 2018–2019; assert the number of nonzero coefficients is monotonically non-increasing as alpha grows.

### H2.5. Residual-based uncertainty (NEW)

Replaces `std = prior_std * (shrunk_mean / max(prior_mean, _MIN_MEAN))` at `qb.py:248`, `rb.py:228`, `wr_te.py:235` — the single biggest tail-pricing risk.

**For `legacy` and `count_aware` paths:** compute the empirical residual std (or, for count families, the model-implied std from the fitted distribution parameters) on the training window. Cache per (position, stat, config) alongside the fitted coefficients.

**For `decomposed` path:** uncertainty falls out of the Monte Carlo composition naturally — no separate std estimate needed.

**Test:** `tests/test_residual_uncertainty.py` — synthetic data with known residual variance; recovered std within 5% of truth; legacy hand-scaled path raises a `DeprecationWarning` when called.

### H3. Per-season Qwen 1.7B narration (template fill only)

**New file:** `llm/templates/season_summary.j2` — Jinja2 template with rigid slots:
```
# Training Season {{ season }}

**Holdout:** {{ holdout_season }}

## Headline metrics (best config)
- Best k: {{ best_k }}
- L1 alpha: {{ best_l1_alpha }}
- Distribution family: {{ best_dist_family }}
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
- Distribution family delta (legacy → count_aware → decomposed): {{ dist_family_table }}

## Qualitative observations
{{ qwen_freeform_notes }}  <!-- 2-3 sentences MAX, low-stakes commentary -->
```

**New file:** `scripts/narrate_season.py` — loads `season_<YYYY>_results.csv`, fills every slot with deterministic numeric values, then sends only the rendered scaffold + raw numbers to Qwen 1.7B asking for 2–3 sentences filling `{{ qwen_freeform_notes }}`. All statistical facts are pinned by the template; Qwen cannot corrupt them. Max 80 tokens for the freeform slot, enforced by llama.cpp.

Output: markdown written both to `docs/training/season_<YYYY>_summary.md` and appended to the brain at `E:/AI Brain/ClaudeBrain/02 Work and Career/NFLStatsPredictor/training/season_<YYYY>.md`.

**Test:** `tests/test_narrate.py` — feed a canned results CSV; mock the Qwen HTTP call; assert the rendered markdown contains every slot value verbatim and the Qwen freeform section is ≤ 80 tokens.

### H4. Cross-season synthesis

**New file:** `scripts/synthesize_training.py` — runs after the full walk-forward completes (2018→2024 holdout-on-next). Aggregates all seven `season_<YYYY>_results.csv` files, picks the config that's **Pareto-optimal across seasons** (lowest mean holdout log-loss *and* lowest variance across seasons — penalizes configs that win one year and tank another). Renders:
- `docs/training/cross_season_summary.md` — ranking table, headline recommendation, per-feature ablation rollup, per-stat distribution-family choice.
- `docs/training/cross_season_reliability.png` — overlay of reliability diagrams across seasons for the recommended config.

Then one Qwen 1.7B narration pass fills a final `{{ rollup_notes }}` slot (3–4 sentences, 120 tokens max) summarizing what held up year-over-year.

### H4.5. Calibration disjointness assertion (NEW)

Defends against the silent train/holdout overlap in `eval/calibration_pipeline.py:154-189`.

**Modify:** `eval/calibration_pipeline.py:154` — at the top of `_fit_models`, add:
```python
overlap = set(train_years) & set(holdout_years)
if overlap:
    raise ValueError(f"train_years and holdout_years overlap: {sorted(overlap)}")
```

**Modify:** `eval/replay_pipeline.py:278-286` — same assertion before calling `build_calibration_rows`.

**New file:** `eval/calibration_fit.py` (also referenced by H5) enforces a stricter four-window discipline: model-train window ⊥ calibrator-fit window ⊥ policy-tune window ⊥ final-eval window. Final 2025 hold-out-hold-out is reserved and untouched until H5 close.

**Test:** `tests/test_calibration_disjoint.py` — overlapping years raise `ValueError` with the offending years in the message.

### H5. Human locks in the final config

Review `cross_season_summary.md` + reliability overlay. Pick the `(k, l1_alpha, dist_family per stat, feature_flags, calibration on/off)` combination. Document the choice and rationale in `docs/ModelingNotes.md`.

**Modify:**
- `models/qb.py`, `models/rb.py`, `models/wr_te.py` — lock in final default `k`, `l1_alpha`, `dist_family per stat`, feature flags.
- `eval/prop_pricer.py` — optional calibration pass gated on `settings.use_calibration`.
- `api/settings.py` — set final `use_calibration` default based on H4 evidence.

**Test:** `tests/test_calibration.py` — fit on synthetic data with known ground-truth mapping; assert recovery within tolerance.

**Brain checkpoint:** project note capturing the final config, the Pareto rationale from H4, the per-stat distribution family choice, and the headline metric delta vs v0.5.1 baseline. This becomes the durable record of why the model looks the way it does after 2026.
**Git checkpoint:** update `VERSIONS.md` with v0.8c entry; tag `v0.8c`.

---

## Phase J — v0.8d-pricing: Pricing & Decision Layer (NEW)

Without no-vig pricing and EV-based selection, the Kalshi paper-trading record is statistically meaningless. This phase must land before pointing the engine at preseason markets.

### J1. No-vig utility

**New file:** `eval/no_vig.py` — `remove_vig_two_sided(over_odds: int, under_odds: int, *, method: Literal["multiplicative", "additive", "shin"] = "multiplicative") -> tuple[float, float]` returning the no-vig over/under probabilities.

- Multiplicative (default): `p_over_no_vig = p_over / (p_over + p_under)`.
- Additive: subtract half the vig from each side's implied probability.
- Shin: power-method weighted by inferred favorite-longshot bias (deferred but stubbed).

**Test:** `tests/test_no_vig.py` —
- -110 / -110 → (0.5, 0.5).
- -150 / +130 → worked example matches multiplicative formula.
- Sum of returned probs equals 1.0 to 1e-9.

### J2. Decision object

**Modify:** `eval/prop_pricer.py` — `price_two_sided_prop` returns a frozen dataclass instead of the current dict:

```python
@dataclass(frozen=True)
class PropDecision:
    player_id: str
    stat: str
    line: float
    model_mean: float
    model_p_over_calibrated: float
    model_p_under_calibrated: float
    market_p_over_no_vig: float
    market_p_under_no_vig: float
    ev_over: float
    ev_under: float
    fair_line: float                # quantile of model dist where P=0.5
    best_book_over: str | None
    best_book_under: str | None
    closing_line: float | None      # filled by Phase K capture; null pre-season
    top_drivers: tuple[str, ...]    # top 3 features by coef × value, length 3
    confidence: Literal["high", "med", "low"]   # feature completeness flag
    recommendation: Literal["over", "under", "no_bet"]
```

`confidence` is `low` if any required feature is null (e.g., weather forecast unavailable, injury feed stale).

### J3. Selection policy

**Modify:** `eval/replay_pipeline.py`:
- Replace the `min_edge=0.05` threshold with EV ranking: `expected_roi = ev_over / abs(stake_over)`.
- `recommendation = "no_bet"` when both `ev_over < min_ev` and `ev_under < min_ev` (default `min_ev = 0.02`).
- Per-player exposure cap (default 1 prop per player per slate); per-game exposure cap (default 4 props per game).
- Drop the `_apply_correlation_penalty` heuristic from parlay path; tag it as `# heuristic — not for headline metrics` until Phase L (post-season).

**Test:** `tests/test_decision_object.py` — schema completeness; `no_bet` rate >40% on a real-season replay (sanity); EV ranking changes top-pick versus raw-edge ranking on at least one known case.

### J4. Settings + brain checkpoint

**Modify:** `api/settings.py` — add `use_no_vig: bool = True`, `min_ev: float = 0.02`, `max_props_per_player: int = 1`, `max_props_per_game: int = 4`, `correlation_penalty_enabled: bool = False`.

**Modify:** `api/schemas.py` — Pick schema gains optional decision-object fields.

**Brain checkpoint:** project note describing the decision-object contract.
**Git checkpoint:** update `VERSIONS.md` with v0.8d-pricing entry; tag `v0.8d-pricing`.

---

## Phase I — v0.8d: Wire Weather to Live Surface + Decision Drawer

Light expansion of the original Phase I. Now that the archive path is proven and Phase J emits decision objects, light up the UI fields left honest-null in Phase B and add a "why this bet" drawer.

### I1. Attach weather + injury to picks

**Modify:** `api/services/replay_service.py` and `evaluation_service.py` — load the weather archive once at sidecar startup via `data.weather.load_archive(seasons)`; left-join by `game_id` when building pick payloads. Attach `weather: {temp_f, wind_mph, precip_in, indoor} | null` and `injury_status: "Q"|"D"|"O"|null` to each pick.

**Modify:** `api/schemas.py` — add optional `weather`, `injury_status`, and the J2 decision-object fields on the Pick schema.

**Frontend schema note:** the existing `WeatherInfo` TS type in `weather-badge.tsx` uses `precip_prob` (forecast semantics). Extend it to also accept `precip_in` (archive quantity) and `indoor: boolean`. Keep `precip_prob` for the forecast path; the badge can render either.

### I2. Weather + injury badges (real data)

**Modify:**
- `desktop/src/components/weather-badge.tsx` — render wind icon + value (red if >15 mph), temp, precip dot, dome badge. Lucide icons.
- `desktop/src/components/injury-pill.tsx` — Q/D/O color-coded pill from `nflverse_loader.load_injuries()`.
- `desktop/src/components/player-card.tsx` — pass real props instead of `null`; "No current feed" / "Status unknown" fallbacks stay as guards.

### I3. "Why this bet" drawer (NEW)

**New component:** `desktop/src/components/decision-drawer.tsx` — opens from the player card; renders:
- Model mean and a quantile sparkline of the distribution (from H1.5 quantile output).
- Calibrated over/under probabilities side-by-side with no-vig market probabilities.
- Expected ROI on each side; the no-bet path explicit when chosen.
- Top 3 feature drivers (e.g., "wind 22 mph", "opp def EPA −0.18 / play", "snap-share trend +6 pts").
- Confidence flag with a tooltip listing any null inputs.

This is the answer to the deep review's "make the app feel less like a black box" point.

### I4. Forecast path for in-season (dormant)

Leave `data/weather.py:load_forecast()` implemented but gated on `settings.use_live_forecast` (default `False`). One-line note in `docs/ModelingNotes.md` pointing to where the flag is and what flipping it does. No call paths activate in-season until that flag is set.

**Git checkpoint:** update `VERSIONS.md` with v0.8d entry; tag `v0.8d`.

---

## Phase K — v0.8e: Realistic Paper Execution (NEW)

The existing `FakePaperAdapter` fills every order at the limit price instantly. P&L from this setup is not predictive. Before Kalshi activation, the ledger must be side-aware and the adapter must include realistic spread/slippage/non-fill behavior.

### K1. Side-aware order events

**Modify:** `api/trading/types.py`:
- `OrderEvent` gains `side: Literal["yes", "no"]` and `action: Literal["open", "close"]`.
- New `Trade` record for closes (links open/close events with realized P&L).
- `PortfolioState.positions` becomes `dict[tuple[MarketRef, Literal["yes","no"]], Position]` instead of `dict[MarketRef, Position]`.

### K2. Side-aware ledger

**Modify:** `api/trading/ledger.py`:
- `_apply_fill` becomes side-aware:
  - `(yes, open)` increases yes-side inventory at weighted-avg price.
  - `(yes, close)` decreases yes-side inventory and books realized P&L = `(close_price - open_avg) * size`.
  - Mirror for the no-side.
- New method `mark_to_market(prices: dict[MarketRef, dict[str, float]])` — called on each tick to update unrealized P&L per `(market, side)`.
- New method `settle(market_ref: MarketRef, outcome: Literal["yes","no"])` — terminal settlement at outcome resolution.
- `persist()` continues to write JSON.

**Test:** `tests/trading/test_side_aware_ledger.py`:
- Yes-buy then yes-sell reduces inventory and books realized P&L correctly.
- No-side and yes-side inventories are tracked independently.
- Mark-to-market updates unrealized without touching realized.
- Settle on `yes` outcome: yes positions pay $1 per contract; no positions pay $0.

### K3. Realistic paper adapter

**Modify:** `api/trading/paper_adapter.py` — add `RealisticPaperAdapter` (keep `FakePaperAdapter` for unit tests):
- Spread injected from a per-stat empirical distribution (default 2¢ on Kalshi-style 0–100 prices).
- Non-fill probability is a logistic function of `|limit_price - current_mid|` (default: 50% non-fill at 5¢ away from mid).
- Partial fills probabilistically (default: 30% chance of 50–80% partial when filled).
- Slippage on market-replay scenarios — fill happens at next-tick mid, not the limit.

**Test:** `tests/trading/test_realistic_paper.py`:
- Non-fills trigger when limit far from mid.
- Partials reduce remaining size and re-queue.
- Across 10k simulated orders, fill rate matches expected distribution within 2σ.

### K4. Exposure-based risk engine

**Modify:** `api/trading/risk.py` — `ExposureRiskEngine` replaces `StaticRiskEngine` (keep static engine as a fallback):
- Worst-case loss per `(market, side, outstanding orders)` — for yes-buy, max loss is `size × limit_price` (price → 0); for no-buy, max loss is `size × (1 - limit_price)`.
- Settlement-calendar awareness (don't enter a market <2 hrs to lock; tunable via `settings.entry_buffer_seconds`).
- Per-side inventory cap (`max_yes_inventory_per_market`, `max_no_inventory_per_market`).
- Daily loss cap and reject-cooldown carry over from `StaticRiskEngine`.

**Test:** `tests/trading/test_exposure_engine.py`:
- Settlement calendar blocks late entries.
- Worst-case loss computed correctly for both sides.
- Inventory caps enforced.

### K5. Wire `use_realistic_paper` flag

**Modify:** `api/settings.py` — add `use_realistic_paper: bool = True` (default true once tests pass).

**Modify:** `api/services/execution_service.py` — pick adapter class via flag.

**Brain checkpoint:** project note on side-aware ledger semantics and the `RealisticPaperAdapter` parameters.
**Git checkpoint:** update `VERSIONS.md` with v0.8e entry; tag `v0.8e`.

---

## Critical Files — Quick Reference (Remaining Phases G→K)

**New:**
- Weather: `data/stadium_coords.py` (✅), `scripts/backfill_weather.py`
- FGFP: `data/upcoming.py`, `data/team_context.py` (extracted helper)
- Modeling: `scripts/train_loop.py`, `scripts/narrate_season.py`, `scripts/synthesize_training.py`, `eval/calibration_fit.py`, `llm/templates/season_summary.j2`
- Pricing: `eval/no_vig.py`
- Execution: `api/trading/paper_adapter.py::RealisticPaperAdapter` (in same file)
- Quote capture: `scripts/capture_kalshi_quotes.py` (season-start)
- Frontend: `desktop/src/components/decision-drawer.tsx`
- Tests: `tests/test_stadium_coords.py` (✅), `tests/test_weather_backfill.py`, `tests/test_upcoming.py`, `tests/test_predict_with_future_row.py`, `tests/test_model_weather.py`, `tests/test_dist_families.py`, `tests/test_l1_path.py`, `tests/test_residual_uncertainty.py`, `tests/test_narrate.py`, `tests/test_calibration.py`, `tests/test_calibration_disjoint.py`, `tests/test_no_vig.py`, `tests/test_decision_object.py`, `tests/trading/test_side_aware_ledger.py`, `tests/trading/test_realistic_paper.py`, `tests/trading/test_exposure_engine.py`
- Docs: `docs/ModelingNotes.md`, `docs/training/season_<YYYY>_*.{csv,png,md}`, `docs/training/cross_season_*.{md,png}`

**Modified:**
- `data/weather.py` — real `load_archive` + `load_forecast`
- `data/nflverse_loader.py` — `load_weekly_with_weather`
- `models/qb.py`, `models/rb.py`, `models/wr_te.py` — statsmodels migration, weather features, count-aware/decomposed dist families, residual std, `predict(future_row=)`, new default `k`/`l1_alpha`
- `eval/prop_pricer.py` — decision object output, no-vig integration
- `eval/replay_pipeline.py` — call `build_upcoming_row`, EV-based selection, exposure caps, no-bet, calibration disjointness assertion
- `eval/calibration_pipeline.py:154` — disjointness assertion
- `api/trading/types.py` — `side` + `action` on `OrderEvent`, new `Trade` event, keyed positions dict
- `api/trading/ledger.py` — side-aware `_apply_fill`, `mark_to_market`, `settle`
- `api/trading/risk.py` — `ExposureRiskEngine`
- `api/services/execution_service.py` — adapter selection via flag
- `api/schemas.py` — weather/injury/decision-object on Pick
- `api/services/replay_service.py`, `evaluation_service.py` — attach weather + injury
- `api/settings.py` — `use_calibration`, `use_live_forecast`, `use_no_vig`, `min_ev`, `max_props_per_*`, `correlation_penalty_enabled`, `use_realistic_paper`, `entry_buffer_seconds`, `max_*_inventory_per_market`
- `desktop/src/components/{weather-badge,injury-pill,player-card}.tsx`, decision drawer
- `VERSIONS.md` — entries for v0.8b/b-fgfp/c/d-pricing/d/e

---

## Explicitly Out of Scope

Belongs to v0.9+ (post-season-start activation):
- Polymarket global (CLOB V2) adapter.
- Polymarket US adapter (separate from global; KYC + Ed25519 signing; regulated DCM).
- **Kalshi live activation** — real `demo-api.kalshi.co` calls, real WebSocket listener, real mapper-to-ticker logic. Swap happens inside `api/trading/kalshi/client.py` and `ws.py`; no callers change.
- Real-money execution on any venue (gated on one full season of paper-trading with green CLV + green no-vig EV).
- Cross-venue arbitrage or market-making strategies.
- Multi-user or remote execution topology.
- Compliance/KYC/geolocation automation.
- Empirical correlated-parlay model (kept as research module with explicit "heuristic" labels in UI; revisit after season-1 data).
- Historical-props warehouse backfill (data not available; capture timestamped Kalshi quotes going forward instead — see Season-Start additions below).

---

## Verification

**G (v0.8b):** `scripts/backfill_weather.py` populates `cache/weather_archive.parquet` with one row per outdoor game for 2018–2025; `uv run python -c "from data.weather import load_archive; print(load_archive([2024]).head())"` returns real temps/winds in imperial units; indoor games (fixed dome + retractable) are flagged `indoor=True` with null numeric fields; all G tests green.

**G.5 (v0.8b-fgfp):** `pytest tests/test_upcoming.py tests/test_predict_with_future_row.py` green; manually call `predict(player_id="X", future_row=build_upcoming_row("X", 2024, 5))` against opp BUF vs. opp MIA — distributions visibly differ; replay output for 2024 is unchanged beyond floating-point tolerance versus pre-FGFP, OR any meaningful delta is documented in `docs/ModelingNotes.md` with an evidence-based rationale.

**H (v0.8c):** `scripts/train_loop.py` produces `docs/training/season_<YYYY>_results.csv` for every walk-forward step 2018→2024; reliability diagrams rendered per (season, position, stat); Qwen 1.7B season-summary markdown exists per season both in `docs/training/` and the brain; `cross_season_summary.md` documents final `(k, l1_alpha, dist_family, feature_flags, calibration)` choice with Pareto rationale and headline deltas vs v0.5.1; `pytest tests/test_dist_families.py tests/test_residual_uncertainty.py tests/test_calibration_disjoint.py tests/test_l1_path.py` green; ablation grid CSV shows `dist_family=count_aware` or `decomposed` outperforming `legacy` on holdout log-loss for at least 4 of 7 walk-forward steps; `docs/ModelingNotes.md` records the locked config.

**J (v0.8d-pricing):** `pytest tests/test_no_vig.py tests/test_decision_object.py` green; replay run on a recent season produces decision objects whose `no_bet` rate is >40% (sanity — most props are not edges); EV ranking changes the top-pick versus raw-edge ranking on at least one known case.

**I (v0.8d):** A Week-1 outdoor game pick on the dashboard shows real wind/temp/precip; a Week-1 indoor game shows a dome badge; a player with an injury designation from nflverse shows Q/D/O pill; null cases still render "No current feed" / "Status unknown"; the decision drawer renders model mean, distribution sparkline, calibrated probs, no-vig probs, EV per side, top 3 drivers, confidence flag.

**K (v0.8e):** `pytest tests/trading/test_side_aware_ledger.py tests/trading/test_realistic_paper.py tests/trading/test_exposure_engine.py` green; running a season replay through `RealisticPaperAdapter` produces a non-fill rate >5% and a per-trade P&L distribution that includes losses (not just instant-fill wins); `mark_to_market` and `settle` produce sane unrealized→realized transitions on a synthetic two-tick scenario.

---

## Season-Start Activation Checklist (post-v0.8e, not in this plan)

When preseason opens (~August 2026), in-season activation is mechanical:

1. Provision a Kalshi demo account; store credentials via `POST /api/secrets/kalshi`.
2. Replace `NotImplementedError`s in `api/trading/kalshi/client.py` with real HTTP calls.
3. Replace `ws.py`'s stub with a real authenticated WebSocket listener.
4. Implement `KalshiMapper.map_signal` using Kalshi's `get_markets` discovery.
5. Flip the venue selector to enabled; change banner to amber "Kalshi demo — mock funds, real venue".
6. Run `tests/trading/test_kalshi_contract.py` against demo (gated on `KALSHI_DEMO_KEY`).
7. Exercise weather forecast path on Week-1 upcoming games.
8. **(NEW)** Start `scripts/capture_kalshi_quotes.py` as a background process the moment NFL preseason markets list. It writes timestamped open/intraday/close quotes to `cache/kalshi_quotes.parquet` keyed by `(market_id, side, timestamp)` so that within 2–3 weeks of regular-season kickoff, the decision object's `closing_line` field can be populated and CLV becomes a real KPI. This is the offseason answer to the deep review's "highest-leverage missing asset" without forcing a backfill of synthetic props.

No file structure changes. No caller changes. That's the point of shipping the scaffolding now.
