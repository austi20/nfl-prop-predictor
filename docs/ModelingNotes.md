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
