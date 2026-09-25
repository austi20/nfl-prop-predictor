# Modeling Notes

Cross-cutting notes about model design choices and known caveats. Phase H
will collapse the open-question section into a locked configuration.

---

## Post-G.5 Sequencing Implementation (v0.8d-preflight through v0.9a-training)

- Weather is now a stable-schema input: missing archives keep the weather
  columns present, unmatched joins mark `indoor=True`, and replay metadata
  reports `weather_archive_available` so H can skip weather ablations when the
  archive is absent.
- Pricing policy now separates model belief from market belief. Two-sided
  American odds are no-vigged before edge/EV decisions, while realized replay
  profit still uses the offered American odds.
- `docs/training/synthetic_props_training.csv` is the default offline market
  dataset for H/J/K prep. Its synthetic-surrogate odds are leakage-safe enough
  for pipeline and policy evaluation, but all result summaries should still be
  labeled synthetic-surrogate rather than live-market profitability.
- Odds, provenance, and outcome fields are explicitly excluded from model
  features via `eval/training_dataset.py::TRAINING_ODDS_FEATURE_EXCLUSIONS`.
- `use_future_row` is wired as a flag path in replay/calibration/evaluation
  and fantasy prediction, but the default remains `False` until Phase H
  ablation confirms it should become the baseline.

---

## Phase G.5 — Future-Game Feature Pipeline (v0.8b-fgfp)

### What landed

- `data/upcoming.py::build_upcoming_row(player_id, season, week, *, position,
  opponent_team, recent_team, ...)` returns a feature dict whose keys are a
  strict superset of the position model's `_build_features` columns. The
  builder appends a stat-zero placeholder row to the historical weekly frame
  and re-runs the position's existing feature builder, so feature semantics
  are guaranteed identical to training. No parallel rolling/lagging logic.
- `models/{qb,rb,wr_te}.py::predict()` gained a `future_row: dict | None = None`
  kwarg. When supplied, the feature vector is built from the dict instead of
  the latest historical row.
- The legacy `opp_team` argument was made optional and emits a
  `DeprecationWarning` when used without `future_row`. It will be removed
  after Phase H.
- `api/settings.py::use_future_row: bool = False` (env: `NFL_APP_USE_FUTURE_ROW`).
  Defaults off — replay and evaluation services still use the latest-row
  path, so 2024 replay output is unchanged. Phase H ablation flips this on
  and treats it as a grid axis.

### What was deferred

- `data/team_context.py::rolling_def_epa` (PBP-derived defensive EPA per
  play and per route) is not extracted yet. The current `merge_group_context`
  helper in `models/feature_utils.py` already produces weekly-stats-derived
  `opp_*_allowed_*` rolling context, which is what models use today. PBP-EPA
  is a Phase H1.5 / H2 feature addition and will be wired alongside
  `dist_family ∈ {legacy, count_aware, decomposed}`.
- Snap-share / route-share trend, teammate-injury swap, and game-environment
  features (implied team total) are spec'd in `plan.md:108-114` for the
  full G.5 vision but rely on data feeds (`load_snap_counts`, `load_injuries`)
  that the current weekly `_build_features` does not consume. The dict
  contract supports adding them — they pass through unchanged via the
  `weather` and arbitrary-key paths — but they are not yet feature inputs.
  Phase H1 weather features land first; richer context follows in H2.

### Known delta vs pre-FGFP replay

The plan's optimistic claim that replay output for 2024 should "not change
beyond floating-point tolerance" when `use_future_row=True` is wishful — the
latest-historical-row hack used whichever opponent the player faced last,
not the upcoming opponent, so flipping the flag will produce a real (and
intended) shift in `opp_*_allowed_*` features and downstream predictions.
That delta is a feature, not a bug — it is the entire point of G.5. Default
remains `False` so the v0.8b replay artifacts stay reproducible until Phase
H runs the ablation grid and locks the config.

---

## Phase H5 Per-stat lock (v0.8c)

Phase H walk-forward training ran an ablation grid over four axes
(`dist_family`, `k`, `l1_alpha`, `use_weather`) for seven holdout seasons
(2019-2025). Per-season results live in `docs/training/season_<YYYY>_results.csv`;
cross-season aggregation is in `docs/training/cross_season_summary.md` and
`docs/training/per_stat_majority_config.csv`. This section records the locks
that ship in v0.8c and the reasoning for each deviation from the auto-generated
majority table.

### Locked defaults

| pos | stat | family | k | l1_alpha | weather | basis |
|---|---|---|---|---|---|---|
| qb | completions | count_aware | 2 | 0.0 | False | 4-way tie at pooled k=2 best (0.7471); 4/7 yearly winners |
| qb | interceptions | count_aware | 2 | 0.0 | False | tight-pack stat at noise floor (spread <0.01); l1=0.0 picked for consistency |
| qb | passing_tds | count_aware | 2 | 0.0 | False | 4-way tie at pooled best (0.6584); k=2 wins 6/7 yearly |
| qb | passing_yards | **decomposed** | 2 | 0.0 | False | decomposed clearly best (0.7572 vs 0.840 count_aware); 5/7 yearly winners |
| rb | carries | count_aware | 2 | 0.0 | False | 4-way tie at pooled best (2.5477); 6/7 yearly winners count_aware |
| rb | rushing_tds | count_aware | 2 | 0.0 | False | tight-pack; legacy 0.0001 better empirically but count_aware preferred for architectural consistency |
| rb | rushing_yards | count_aware | 2 | 0.0 | False | count_aware best at k=2 (1.1303); l1=0.001 was a 7e-5 improvement, dropped for simplicity |
| wr_te | receiving_tds | count_aware | 2 | 0.0 | False | tight-pack; legacy 0.0002 better empirically but count_aware preferred for consistency |
| wr_te | receiving_yards | count_aware | 2 | 0.0 | False | l1=0.1 was 0.001-0.005 better empirically; dropped for simplicity (single l1 per model) |
| wr_te | receptions | **decomposed** | 2 | 0.0 | False | decomposed clearly wins (0.8019 vs 0.8040 count_aware); 6/7 yearly winners |

These per-stat locks are realized by the per-position default `dist_family` in
`fit()`:

- `models/qb.py`: `dist_family="decomposed"` — passing_yards routes through
  Monte Carlo composition; the three count stats automatically use the
  count_aware NegBin/Poisson path because decomposed is a superset of
  count_aware for non-decomposable stats.
- `models/rb.py`: `dist_family="count_aware"` — rushing_yards uses the
  count_aware quantile companion path; carries and rushing_tds use NegBin/Poisson.
- `models/wr_te.py`: `dist_family="decomposed"` — receptions routes through
  the targets x catch_rate composition; receiving_yards and receiving_tds
  automatically use count_aware paths.

All three models default to `k=2`, `l1_alpha=0.0`, `use_weather=False`.

Since v0.9-m6, `k` only sets the cold start (future season) GLM weight. The
in season shrinkage toward the league prior is a per stat constant fitted by
least squares (`models/shrinkage.py`, `models/shrinkage_weights.json`), because
`n/(n+k)` counted same season games and collapsed early weeks onto the mean.
Evidence in `docs/diag/shrinkage_tuning.md`.

### Why these knobs (universal findings)

1. **k=2 is universally best.** Pooled holdout log_loss is monotonically
   increasing in `k` for every single (position, stat). The plan's grid
   {2, 4, 6, 8, 12, 16} should narrow to k=2 in production. A future
   ablation could test k<2 (i.e. k=1 or no shrinkage at all) to see if the
   monotone trend continues.

2. **`use_weather=False` everywhere.** Marginal pooled effect across all 10
   stats ranged -0.0001 to +0.0076 log_loss (mostly noise). Yearly contests
   pick weather=True for some stats and False for others — sampling noise
   on top of a near-zero true effect. With only ~2,227 outdoor games in
   2018-2025, the weather coefficients can't be fit reliably. The auto-
   generated `per_stat_majority_config.csv` had several `use_weather=True`
   selections that were 1-vote tiebreaks; we discarded them. A future
   H2.1 mini-grid could test weather only on outdoor-only subsets.

3. **`l1_alpha=0.0` everywhere.** L1 effects ranged 0.0001-0.005 log_loss
   per stat, with no consistent direction. Some stats marginally prefer
   l1=0.1 (receiving_yards, interceptions); others prefer l1=0.0
   (rushing_tds, receiving_tds). The single-l1-per-model architecture
   doesn't support per-stat l1; we lock 0.0 and accept a 0.0007-0.005
   penalty on receiving_yards and interceptions. Per-stat l1 is a
   candidate for a v0.9 refactor.

4. **`use_opponent_epa`, `use_rest_days`, `use_home_away` were never varied.**
   The shipped 144-config grid only varied four axes; the spec listed seven.
   These three flags ship locked False because we have no evidence either
   way. A future H2.1 grid should re-test them on the locked (k=2, l1=0,
   weather=False) baseline.

### dist_family architectural facts

- `decomposed` is functionally identical to `count_aware` for 7 of 10 stats.
  Decomposition is only implemented for `qb/passing_yards` (attempts × ypa),
  `rb/rushing_yards` (carries × ypc), and `wr_te/receptions` (targets ×
  catch_rate). For the other seven stats, predictions are byte-identical
  between the two families. The auto-generated majority CSV reports
  `dist_family=decomposed` for some of these arbitrary-tiebreak cases;
  this lock prefers `count_aware` (the actual underlying model) for honesty.

- `legacy` is marginally better than `count_aware` for two TD/score-event
  stats (`rb/rushing_tds` by 0.0001, `wr_te/receiving_tds` by 0.0002). The
  gap is below noise. We chose `count_aware` for these stats anyway because
  (a) all count stats using one family is architecturally cleaner and (b)
  count_aware's principled zero-mass behavior is a future-proofing
  advantage. Documented as a deviation from empirical optimum.

### Tight-pack stats (near the noise floor)

Four count stats have the entire 144-config grid producing log_loss within
~0.01 of the best:

| Stat | spread (worst − best) in 2024 |
|---|---|
| `qb/interceptions` | 0.0048 |
| `wr_te/receiving_tds` | 0.0109 |
| `rb/rushing_tds` | 0.0138 |
| `qb/passing_tds` | 0.0213 |

These are score-event count stats where the base rate dominates the prediction.
The model is near the irreducible loss floor for these four. Future "no
improvement" verdicts on these stats during v0.9 work should be interpreted as
"already optimal," not as a bug.

### Season-by-season anomalies

- **2019 has 288 fit_errors** (20% of QB rows). With only 2018 as training
  data, regularized count_aware/decomposed QB models don't converge. The
  2019 QB yearly winners are constrained to legacy + (count_aware/decomposed
  at l1=0). Don't let those four 1-vote QB winners drive lock decisions.
- **2020 is mildly worse than 2021+** (mean best log_loss 0.92 vs 0.90).
  Probably the COVID/empty-stadium effect, but not pathological.
- **Models steadily improve 2019 → 2023** as cumulative training data grows.
  2024-2025 plateau slightly above 2023. No outlier season requires special
  handling.

### Phase H5 calibration deferral

`api/settings.py::use_calibration: bool = False`. Cross-season mean
`max_reliability_dev` for the locked configs ranged 0.44-0.48 — high enough
to motivate calibration in principle, but the metric is computed against
**synthetic surrogate odds**, not real captured market lines. A calibrator
fit on this data may shift probabilities in the wrong direction once we
have real Kalshi quotes (see plan.md Season-Start checklist). Recommendation:
keep `use_calibration=False` until v0.9 ships real captured quotes, then fit
a calibrator on real lines and reassess.

### What was NOT done in H5 (deferred to v0.9)

- **Per-stat L1**: noted above. Cost ~0.001-0.005 log_loss on receiving_yards
  and interceptions.
- **Per-stat weather flag**: weather features may help on outdoor-only
  subsets but 2,227 games is too thin to detect.
- **Re-test `use_opponent_epa` / `use_rest_days` / `use_home_away`**:
  shipped grid did not vary these.
- **Calibrator on real captured quotes**: cannot fit until live Kalshi
  capture (`scripts/capture_kalshi_quotes.py`) accumulates data.

---
