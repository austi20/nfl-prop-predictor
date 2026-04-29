# Plan: Phase H Walk-Forward Training + Season Activation

**Last updated:** 2026-04-28
**Active version target:** v0.8c (Phase H)
**Previous plan archived at:** `docs/plan_archive_pre_h.md`

---

## Context for future reads

This plan covers only **work not yet shipped**. Everything before v0.9a-training is in `VERSIONS.md` and `docs/plan_archive_pre_h.md`. Read those for historical decisions, not for active work.

### What is already shipped (do not re-implement)

Per `VERSIONS.md`, the following phases are complete and locked:

| Phase | Version | Deliverable |
|-------|---------|-------------|
| G | v0.8b | Open-Meteo Archive weather backfill (`cache/weather_archive.parquet`) + `load_weekly_with_weather()` |
| G.5 | v0.8b-fgfp | `data/upcoming.py::build_upcoming_row()`; `predict(future_row=...)` on QB/RB/WR-TE |
| training data | v0.8c-h2-session-c | `docs/training/synthetic_props_training.csv` (**144,414** rows @ 2026-04-28, seasons **2019–2025** labeled props; surrogate odds; 2025 is now consumed as an H4 voting holdout) |
| preflight | v0.8d-preflight | Stable weather schema, train/holdout disjoint guards, SSE cursor fix |
| J | v0.8e-pricing | `eval/no_vig.py`, `PropDecision` dataclass, EV-ranked pick selection, `no_bet` handling |
| K | v0.8f-execution | Side-aware `OrderEvent`, `RealisticPaperAdapter`, `ExposureRiskEngine` |
| I | v0.8g-ui | Decision drawer, weather/injury payloads on picks |
| training hooks | v0.9a-training | `eval/training_dataset.py`, `use_future_row` flag |

**Training ingredients are cached locally:**
- `cache/weekly_2014-...-2025.parquet` — 217,487 rows × 115 cols, full nflverse weekly history
- `cache/weather_archive.parquet` — 2,227 outdoor games 2018–2025 (indoor games default `indoor=True` + null numerics)
- `cache/schedules_2018-...-2025.parquet`, `cache/injuries_2015-...-2025.parquet`
- `docs/training/synthetic_props_training.csv` — labeled `(player_id, season, week, stat, line, …, outcome_over)` rows for **2019–2025**. All seven seasons are used for H4 majority voting; true **`final_eval`** must be a post–last-holdout season or out-of-band protocol.

**Not yet built:** the joined ML training frame `(X_features, y_outcome, market_prob)` per row. Phase H builds this inside `scripts/train_loop.py` by calling `load_weekly_with_weather()` for the feature base, then joining synthetic props for labels.

### Key flags and current defaults

- `NFL_APP_USE_FUTURE_ROW=false` — gates Phase G.5 path; Phase H ablation flips to `true` if evidence supports.
- `NFL_APP_USE_LIVE_FORECAST=false` — Open-Meteo forecast stub; archive only until preseason.
- `NFL_APP_USE_CALIBRATION` — set by H5 based on cross-season evidence.
- Kalshi adapter raises `NotImplementedError("Kalshi scaffold — activate in-season")`. RSA-PSS signing is real and tested.

---

## Phase H — v0.8c: Walk-Forward Training Loop + Calibration

Per-season walk-forward training driven by a **deterministic harness**, not the LLM. Qwen3 1.7B's role is narration only: structured template-fill into brain notes after each season completes. This phase focuses on **statistical accuracy**, not prop calculations.

**Why walk-forward:** training on year N → holdout-testing on N+1 → advancing is the correct methodology for time-series models. Prevents leakage that plain k-fold CV allows.

**Why deterministic loop, not LLM-driven:** 1.7B cannot reliably judge statistical quality; LLM-iterated tuning leaks the holdout into training via multiple-comparisons. Loop stops on numeric criteria. LLM writes the notes, never decides.

### H1. Statsmodels migration + weather features (flag-guarded)

**Note on filenames:** actual model files are `models/qb.py`, `models/rb.py`, `models/wr_te.py`.

**Note on GLM backend:** current models use sklearn `GammaRegressor`. Phase H requires AIC introspection (for H3 narration), L1 regularization (H2), and family flexibility (H1.5). Statsmodels covers all three, but raw `GLM.fit_regularized()` does not expose `.aic`, so the regularized path must use an active-set refit (or equivalent wrapped metadata) before H3/H4 consume those results. Migration plan: switch all three models to `statsmodels.formula.api` Gamma GLM at H1 start. Default behavior (`l1_alpha=0.0`, no weather, legacy family) must produce identical predictions to within floating-point tolerance — verify this before adding weather features. Mixing backends is not acceptable.

**Modify:** `models/qb.py`, `models/rb.py`, `models/wr_te.py` — `_build_features(df, *, use_weather: bool = False)` adds (for outdoor games only; zero for indoor/null):
- `wind_mph` — affects passing_yards, passing_tds most
- `precip_in` — affects completions, receptions
- `temp_f_minus_60` — mild effect on passing (centered so dome games hit baseline at 0)
- `wind_x_pass_attempt_rate` — interaction term, QB model only

Features are additive; GLM fitting stays stable. Shrinkage applies to the player-specific intercept; weather coefficients pool across all players. The `use_weather` flag is what the ablation grid (H2) toggles — no duplicated model classes.

**Test:** `tests/test_model_weather.py` — train QB on 2018–2024 with/without weather; assert AIC delta is within tolerance; assert `use_weather=True` calls the weather-aware loader; statsmodels migration produces same predictions as old sklearn baseline to `1e-2`; deterministic seed.

### H1.5. Stat-specific distribution architecture

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

**Grid axis added:** `dist_family ∈ {legacy, count_aware, decomposed}`. Phase H4’s **per-stat majority vote** picks a different `config_hash` (and thus often a different family) per `(position, stat)` across holdout years; that’s expected.

**Test:** `tests/test_dist_families.py` — count-aware path produces non-zero probability for `P(TD ≥ 0)` exactly (Poisson/NegBin reach zero); decomposed receptions match a hand-computed example.

### H2. Ablation grid + L1 regularization path

**Grid dimensions** (per run):
- `use_weather ∈ {True, False}`
- `use_opponent_epa ∈ {True, False}` (opponent defensive EPA, already available in nflverse)
- `use_rest_days ∈ {True, False}`
- `use_home_away ∈ {True, False}`
- `dist_family ∈ {legacy, count_aware, decomposed}` (new from H1.5)
- `k ∈ {2, 4, 6, 8, 12, 16}` — shrinkage constant
- `l1_alpha ∈ {0.0, 0.001, 0.01, 0.1}` — L1 regularization; `0.0` means plain GLM

Full grid = `2^4 × 3 × 6 × 4 = 1152` configs × **seven** expanding-window walk-forward holdouts (**2019–2025**) = ~**8064** config × step cells at full grid size (this repo’s locked `train_loop` grid may be a smaller Cartesian subset—see `scripts/train_loop.py`). Each GLM fits in <1 second on CPU; total wall-time scales with step count. Because **2025** is the last simulated holdout for H4 voting, treat any “final_eval after tuning” window as **post–last holdout** (see H4.5 note) so that year is not also claimed as a pristine lock.

**L1 regularization** replaces hand-tuned "variable weighting." At nonzero `l1_alpha`, coefficients on useless features collapse to zero automatically. Ablation flags remain for feature categories you want to force off regardless (e.g., "does weather help on 2019 specifically?").

**Modify:** `models/qb.py`, `models/rb.py`, `models/wr_te.py` — accept `l1_alpha` parameter; when nonzero, fit via `statsmodels.GLM.fit_regularized(alpha=l1_alpha, L1_wt=1.0, refit=True)` (or an equivalent wrapper that preserves `.aic`) instead of plain `fit()`.

**New file:** `scripts/train_loop.py` — runs the full ablation grid for one season; writes `docs/training/season_<YYYY>_results.csv` per walk-forward step.

**Test:** `tests/test_l1_path.py` — fit a QB model across the alpha grid on 2018–2019; assert the number of nonzero coefficients is monotonically non-increasing as alpha grows.

### H2.5. Residual-based uncertainty

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
{{ qwen_freeform_notes }}
```

**New file:** `scripts/narrate_season.py` — loads `season_<YYYY>_results.csv`, fills every slot with deterministic numeric values, then sends only the rendered scaffold + raw numbers to Qwen 1.7B asking for 2–3 sentences filling `{{ qwen_freeform_notes }}`. All statistical facts are pinned by the template; Qwen cannot corrupt them. Max 80 tokens for the freeform slot, enforced by llama.cpp.

Output: markdown written both to `docs/training/season_<YYYY>_summary.md` and appended to the brain at `E:/AI Brain/ClaudeBrain/02 Work and Career/NFLStatsPredictor/training/season_<YYYY>.md`.

**Test:** `tests/test_narrate.py` — feed a canned results CSV; mock the Qwen HTTP call; assert the rendered markdown contains every slot value verbatim and the Qwen freeform section is ≤ 80 tokens.

### H4. Cross-season synthesis

**New file:** `scripts/synthesize_training.py` — runs after the full walk-forward completes (holdout seasons **2019–2025**; missing `season_<YYYY>_results.csv` files are skipped with a warning). Aggregates all available `season_<YYYY>_results.csv` files and:

1. **H5 primary output:** for each **`(position, stat)`**, selects the `config_hash` that **wins on the most holdout years**. A yearly winner is the valid fit (`convergence_flag` ∈ {`ok`, `constant_fallback`}) with **lowest holdout `log_loss`** for that target in that year. **Ties** in vote count break on **lower mean `log_loss` pooled across all loaded seasons** for that `(position, stat, config)`.
2. **Reference:** keeps the legacy **global** ranking (mean holdout log-loss **plus** 0.5×std across seasons, averaging over all stats first) as a single-config benchmark only—not the production default when using per-stat configs.

Renders:
- `docs/training/per_stat_majority_config.csv` — **lock table** for H5 (one row per stat with `vote_count`, `winning_seasons`, knobs).
- `docs/training/cross_season_summary.md` — majority table, ablations, pooled-across-seasons reference, global benchmark section.
- `docs/training/cross_season_reliability.png` — reliability deviation trend: mean `max_reliability_dev` by season using each stat’s majority config.

Then one Qwen 1.7B narration pass fills `{{ rollup_notes }}` (3–4 sentences, 120 tokens max).

**Test:** `tests/test_synthesize_training.py`.

### H4.5. Calibration disjointness assertion

**Note:** preflight guards already added in v0.8d. H4.5 elevates them to a stricter four-window discipline:
model-train ⊥ calibrator-fit ⊥ policy-tune ⊥ final-eval. Because **2025** is included as the **seventh walk-forward holdout** for grid search and majority voting, the calendar year that was previously described as “final-eval only” is **no longer pristine**—reserve **`final_eval`** to a **later** season or out-of-band protocol documented in `docs/ModelingNotes.md`.

**New file:** `eval/calibration_fit.py` (also referenced by H5) enforces the four-window split.

**Test:** `tests/test_calibration_disjoint.py` — overlapping years raise `ValueError` with the offending years in the message. (Existing v0.8d guard test may already cover the basic case; expand to four-window scenario.)

### H5. Human locks in the final config

Review `cross_season_summary.md` + `per_stat_majority_config.csv` + reliability deviation trend. Lock **`(k, l1_alpha, dist_family, feature_flags)` per stat** from the majority table (not the global benchmark row). Set calibration from evidence. Document in `docs/ModelingNotes.md`.

**Modify:**
- `models/qb.py`, `models/rb.py`, `models/wr_te.py` — lock in final default `k`, `l1_alpha`, `dist_family per stat`, feature flags.
- `eval/prop_pricer.py` — optional calibration pass gated on `settings.use_calibration`.
- `api/settings.py` — set final `use_calibration` default based on H4 evidence.

**Test:** `tests/test_calibration.py` — fit on synthetic data with known ground-truth mapping; assert recovery within tolerance.

**Brain checkpoint:** project note capturing per-stat majority rationale from H4, any deviations you chose from the CSV, and headline metric delta vs v0.5.1 baseline.

**Git checkpoint:** update `VERSIONS.md` with v0.8c entry; tag `v0.8c`.

---

## Phase H Verification (Definition of Done)

`scripts/train_loop.py` produces `docs/training/season_<YYYY>_results.csv` for every walk-forward step (**seven** holdouts, **2019–2025**); reliability deviation trend rendered for locked per-stat configs; Qwen 1.7B season-summary markdown exists per season both in `docs/training/` and the brain; `per_stat_majority_config.csv` + `cross_season_summary.md` document the **per-stat** lock derived from yearly winners (H4) plus headline deltas vs v0.5.1; `pytest tests/test_dist_families.py tests/test_residual_uncertainty.py tests/test_calibration_disjoint.py tests/test_l1_path.py tests/test_model_weather.py tests/test_narrate.py tests/test_synthesize_training.py` green; ablation evidence remains diagnostic; `docs/ModelingNotes.md` records the locked per-stat configs.

---

## Token Map for Phase H Implementation

Estimated cost of full Phase H execution under various skill stacks. Sonnet 4.6 input ≈ $3/MTok, output ≈ $15/MTok.

### Per-sub-phase weight

| Sub-phase | Files touched | New lines (~) | Iteration risk |
|-----------|---------------|---------------|----------------|
| H1 | 3 model files + `tests/test_model_weather.py` | 200–400 | High — statsmodels parity check is critical |
| H1.5 | 3 model files + new `StatDistribution` class + `tests/test_dist_families.py` | 400–700 | High — new architecture |
| H2 | 3 model files + `scripts/train_loop.py` + `tests/test_l1_path.py` | 500–800 | Medium — `train_loop.py` is biggest single file |
| H2.5 | 3 model files + `tests/test_residual_uncertainty.py` | 100–200 | Low — narrow refactor |
| H3 | `llm/templates/season_summary.j2` + `scripts/narrate_season.py` + `tests/test_narrate.py` | 150–250 | Low — fully specified |
| H4 | `scripts/synthesize_training.py` | 200–300 | Low — single script |
| H4.5 | `eval/calibration_fit.py` + `tests/test_calibration_disjoint.py` | 100–150 | Low — guards exist |
| H5 | 3 model files + `api/settings.py` + `eval/prop_pricer.py` + `tests/test_calibration.py` | 150–250 | Low — config lock |

### Naive token estimate (no optimization)

| Bucket | Tokens |
|--------|--------|
| Plan re-reads (~60K × 3 sessions) | 180K |
| File reads w/ iteration | 150–200K |
| Code output (1500–2500 lines × ~40 tok/line) | 80–120K |
| Skill overhead (8× brainstorm, 8× verification, review) | 130–180K |
| **Total** | **540–680K** |

At rough 65/35 input/output split: **~$3–6** in API spend.

### Optimized estimate (apply all three optimizations below)

| Bucket | Tokens |
|--------|--------|
| `phase_h_spec.md` distill (one-time) | 10K |
| Spec re-reads (~10K × 3 sessions) | 30K |
| File reads w/ iteration | 130–170K |
| Code output | 80–120K |
| Skill overhead (2× brainstorm, 2× verification, 1× review) | 50–70K |
| **Total** | **300–400K** |

**Net savings: ~200–300K tokens (~40–45%).**

---

## Token Optimizations

Apply all three before starting H1.

### 1. Plan distillation (biggest win)

This `plan.md` is itself the distilled artifact (down from ~60K → ~12K tokens). Each H sub-session reads this file, not the archived plan. If plan grows during implementation, refresh by truncating completed sub-phases rather than carrying them forward.

**Save:** ~150K across 3 sessions.

### 2. Skip brainstorming for tightly-specified sub-phases

Phase H is unusually well-specified — file paths, function signatures, grid dimensions, and test assertions are all exact. Brainstorming only earns its tokens where ambiguity exists.

| Sub-phase | Brainstorm? | Why |
|-----------|-------------|-----|
| H1 | No | Statsmodels migration is mechanical; parity test pins behavior |
| H1.5 | **Yes** | NegBin vs QuantReg vs decomposed composition has design choices (Monte Carlo sample count, dispersion fallback threshold, hurdle trigger) |
| H2 | **Yes** | `train_loop.py` checkpoint format, results CSV schema, parallelism strategy across the 1152-config grid all genuinely ambiguous |
| H2.5, H3, H4, H4.5, H5 | No | Each fully specified above |

**Save:** ~35–45K.

### 3. Batch verification, not per sub-phase

Run `superpowers:verification-before-completion` only at:
- End of H1 (statsmodels parity is the load-bearing assertion)
- End of H2 (ablation grid is where leakage bugs hide)
- Final H5 close (full Phase H verification per Definition of Done)

Skip mid-phase verification on H1.5, H2.5, H3, H4, H4.5 — their tests are tight and run cheaply.

**Save:** ~90–120K.

---

## Recommended Execution Sequence

Model switching is user-side only (`/model sonnet-4-6` or `/model opus-4-7`). Claude will say `>>> SWITCH TO <MODEL> <<<` at each transition point so you know when to run the command.

**Per-step message budget (Pro 5h session, ~45 Sonnet / ~15 Opus messages per window):**

| Sub-phase | Model | Est. messages |
|-----------|-------|---------------|
| Pre-flight | Sonnet 4.6 | 2-3 |
| H1 statsmodels migration | Sonnet 4.6 | 8-12 |
| H4.5 calibration disjoint | Sonnet 4.6 | 2-3 |
| H1.5 brainstorm | Opus 4.7 | 2-3 |
| H1.5 implementation | Sonnet 4.6 | 8-12 |
| H2.5 residual refactor | Sonnet 4.6 | 4-6 |
| H2 brainstorm | Opus 4.7 | 2-3 |
| H2 train_loop.py | Sonnet 4.6 | 10-15 |
| H3 narration | Sonnet 4.6 | 5-7 |
| H4 synthesis | Sonnet 4.6 | 5-7 |
| H5 review + config lock | Opus 4.7 | 3-4 |
| H5 implementation + verify | Sonnet 4.6 | 5-8 |

Full Phase H = **3-4 separate 5h sessions** even optimized.

---

### Session A — Pre-flight + H1 + H4.5 (~25-30 Sonnet messages)

```
>>> SWITCH TO SONNET 4.6 <<<
```

1. **Pre-flight** (~15K tokens):
   - Confirm this file is up to date with `VERSIONS.md`.
   - Snapshot current `_feature_cols` + `predict()` signatures from 3 model files for parity reference.
   - `uv run pytest -q` baseline — record passing count (240 as of v0.9a).

2. **H1** — statsmodels migration + weather features:
   - Implement in 3 model files; parity test gates merge.
   - Verify (`uv run pytest tests/test_model_weather.py`) before proceeding.

3. **H4.5** — calibration disjointness (parallel-capable, independent of model changes):
   - Can dispatch as parallel agent while H1 wraps up.

```
>>> END SESSION A — window ~exhausted <<<
>>> wait for 5h rolling window to reset <<<
```

---

### Session B — H1.5 + H2.5 (~12 Sonnet + 3 Opus messages)

```
>>> SWITCH TO OPUS 4.7 <<<
```

4. **H1.5 brainstorm** — dist family architecture (NegBin/QuantReg/decomposed):
   - Resolve: Monte Carlo sample count, dispersion fallback threshold, hurdle trigger threshold.
   - Output: locked design decisions before touching code.

```
>>> SWITCH TO SONNET 4.6 <<<
```

5. **H1.5 implementation** — stat-specific distribution architecture + `tests/test_dist_families.py`.

6. **H2.5** — residual-based uncertainty refactor + `tests/test_residual_uncertainty.py`:
   - Falls naturally out of H1.5 model file touches.

```
>>> END SESSION B <<<
```

---

### Session C — H2 (~15 Sonnet + 3 Opus messages)

```
>>> SWITCH TO OPUS 4.7 <<<
```

7. **H2 brainstorm** — `train_loop.py` design:
   - Resolve: results CSV schema, checkpoint format, parallelism strategy for 1152-config grid.
   - Output (Session C documented in `VERSIONS.md` **`v0.8c-h2-session-c`**, then corrected by the H4 reporting cleanup): expanding-window **seven** holdouts (**2019–2025**), frozen **`season_<YYYY>_results.csv`** columns, **`docs/training/synthetic_props_training.csv`** multi-year backfill (**2019–2025**). Since **2025** is the last simulated holdout for config voting, choose a **post–last-holdout** or strictly held-out protocol for true `final_eval` (see H4.5). Checkpoint + worker strategy: finalize with Sonnet alongside `train_loop.py` unless/until patched.

```
>>> SWITCH TO SONNET 4.6 <<<
```

8. **H2 implementation** — ablation grid + L1 path + `scripts/train_loop.py` + `tests/test_l1_path.py`:
   - Verify (`uv run pytest tests/test_l1_path.py`) before running the grid.

```
>>> END SESSION C <<<
```

**Off-LLM compute window:** `uv run python scripts/train_loop.py` for all **seven** walk-forward holdouts. Start after Session C verifies green.

---

### Session D — H3 + H4 (~15 Sonnet messages)

```
>>> SWITCH TO SONNET 4.6 <<<
```

9. **H3** — `llm/templates/season_summary.j2` + `scripts/narrate_season.py` + `tests/test_narrate.py`.

10. **H4** — `scripts/synthesize_training.py` (independent, dispatch as parallel agent):
    - Per-**(position, stat)** **majority vote** across holdout `season_<YYYY>_results.csv` files (**2019–2025** as available).
    - Writes `per_stat_majority_config.csv`, `cross_season_summary.md`, reliability deviation trend PNG.

```
>>> END SESSION D <<<
```

---

### Session E — H5 close (~4 Opus + 8 Sonnet messages)

```
>>> SWITCH TO OPUS 4.7 <<<
```

11. **H5 review** — read `cross_season_summary.md` + **`per_stat_majority_config.csv`**, lock **per-stat** `(k, l1_alpha, dist_family, feature_flags, calibration on/off)`.

```
>>> SWITCH TO SONNET 4.6 <<<
```

12. **H5 lock** — write final defaults into 3 model files + `api/settings.py` + `eval/prop_pricer.py` + `tests/test_calibration.py`.
    - Brain checkpoint.
    - `uv run pytest -q` full suite.
    - Update `VERSIONS.md` v0.8c entry, tag `v0.8c`.

---

## Critical Files (Phase H)

**Modify:** `models/qb.py`, `models/rb.py`, `models/wr_te.py`, `eval/prop_pricer.py`, `api/settings.py`, `eval/calibration_pipeline.py`, `eval/replay_pipeline.py`

**Create:** `scripts/train_loop.py`, `scripts/narrate_season.py`, `scripts/synthesize_training.py`, `eval/calibration_fit.py`, `llm/templates/season_summary.j2`, `docs/ModelingNotes.md` (extend existing)

**Tests:** `tests/test_model_weather.py`, `tests/test_dist_families.py`, `tests/test_l1_path.py`, `tests/test_residual_uncertainty.py`, `tests/test_narrate.py`, `tests/test_synthesize_training.py`, `tests/test_calibration_disjoint.py`, `tests/test_calibration.py`

**Cached training inputs (already built):** `cache/weekly_2014-...-2025.parquet`, `cache/weather_archive.parquet`, `cache/schedules_*.parquet`, `cache/injuries_*.parquet`, `docs/training/synthetic_props_training.csv`

---

## Explicitly Out of Scope (defer to v0.9+)

- Polymarket global (CLOB V2) and Polymarket US adapters
- Kalshi live activation (real `demo-api.kalshi.co` HTTP/WS) — see Season-Start checklist
- Real-money execution (gated on one full season of paper-trading with green CLV + green no-vig EV)
- Cross-venue arbitrage or market-making strategies
- Multi-user or remote execution topology
- Compliance/KYC/geolocation automation
- Empirical correlated-parlay model (kept as research module with explicit "heuristic" labels)
- Historical-props warehouse backfill (capture timestamped Kalshi quotes going forward instead)

---

## Season-Start Activation Checklist (post-Phase H, ~August 2026)

When preseason markets list, in-season activation is mechanical. No file structure changes. No caller changes.

1. Provision a Kalshi demo account; store credentials via `POST /api/secrets/kalshi`.
2. Replace `NotImplementedError`s in `api/trading/kalshi/client.py` with real HTTP calls.
3. Replace `ws.py`'s stub with a real authenticated WebSocket listener.
4. Implement `KalshiMapper.map_signal` using Kalshi's `get_markets` discovery.
5. Flip the venue selector to enabled; banner to amber "Kalshi demo — mock funds, real venue".
6. Run `tests/trading/test_kalshi_contract.py` against demo (gated on `KALSHI_DEMO_KEY`).
7. Exercise weather forecast path on Week-1 upcoming games (flip `NFL_APP_USE_LIVE_FORECAST=true`).
8. Start `scripts/capture_kalshi_quotes.py` as a background process the moment NFL preseason markets list. Writes timestamped open/intraday/close quotes to `cache/kalshi_quotes.parquet` keyed by `(market_id, side, timestamp)`. Within 2–3 weeks of regular-season kickoff, `PropDecision.closing_line` populates and CLV becomes a real KPI.

This is the offseason answer to the deep review's "highest-leverage missing asset" without forcing a backfill of synthetic props.
