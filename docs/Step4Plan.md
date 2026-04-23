# Step 4 Active Tracker

## Purpose

Step 4 is about turning the existing replay, pricing, and parlay scaffolding into a reproducible local paper-trading system for the 2024 and 2025 seasons. This document is the active execution tracker for Step 4 work, while [plan.md](plan.md) remains the macro roadmap and [VERSIONS.md](../VERSIONS.md) remains the version log; it also serves as the bridge into the Step 5 through Step 7 app and live-ops work.

## Current State Snapshot

- Local replay path already exists.
- Two-sided prop pricing, pick settlement, and paper-trade summaries already exist.
- Lightweight parlay candidate generation already exists.
- Minimal Odds API client exists, but Step 4 does not depend on historical Odds API replay.
- Calibration exists as scaffolding and may be plugged in later, but Step 4 must run without it.

## Step 4 Definition Of Done

Step 4 is complete when a local historical props file can be replayed end-to-end for the 2024 and 2025 seasons with no manual code edits, and the replay emits stable singles and parlay outputs plus machine-readable and Markdown reports under `docs/`.

The replay scope for Step 4 is limited to this stat surface:

- `passing_yards`
- `passing_tds`
- `interceptions`
- `completions`
- `rushing_yards`
- `carries`
- `rushing_tds`
- `receptions`
- `receiving_yards`
- `receiving_tds`

Step 4 reports must include:

- overall ROI after vig
- weekly breakdowns
- book-level breakdowns
- stat-level breakdowns
- season-level breakdowns

Calibration remains optional during Step 4. Replay must work in uncalibrated mode and may optionally consume a saved calibrator when one exists.

Step 4 has two completion gates:

1. Engineering-complete: replay is reproducible, documented, and emits full artifacts.
2. Strategy-complete: the selected replay policy achieves non-negative to positive ROI after vig on the tracked evaluation set. If ROI is still weak, Step 4 remains open for policy or model iteration even if the pipeline itself is stable.

## Step 4 Tracker

### `v0.4.3` Replay Contract Hardening

Goal: freeze the canonical local props replay contract and make replay behavior deterministic on supported inputs.

Completion signal: a local props file with the canonical schema can be filtered and replayed without code edits, and invalid rows fail or skip in clearly documented ways.

Artifacts to update:

- `docs/Step4Plan.md`
- replay CLI help or docs
- replay validation tests

- [x] Freeze the canonical local props file schema.
- [x] Document required columns exactly once in this file: `player_id`, `season`, `week`, `stat`, `line`, `over_odds`, `under_odds`.
- [x] Document optional columns exactly once in this file: `book`, `game_id`, `recent_team`, `opponent_team`, `opp_team`, `market_source`, `pulled_at`.
- [x] Normalize `opp_team` and `opponent_team` into one internal opponent field.
- [x] Validate duplicates, missing odds, unsupported stats, and rows with no matched actual outcome.
- [x] Add replay CLI filters for `season`, `week`, `stat`, and `book` so small slices can run before a full replay.
- [x] Keep deterministic replay behavior for the same inputs and flags.

Canonical local props replay schema:

| Column | Required | Notes |
| --- | --- | --- |
| `player_id` | Yes | Stable player identifier used by the projection and outcome-join path. |
| `season` | Yes | NFL season year for the prop row. |
| `week` | Yes | NFL week used for replay slicing and actual-outcome joins. |
| `stat` | Yes | Must be one of the supported Step 4 stats listed above. |
| `line` | Yes | Sportsbook line used for settlement. |
| `over_odds` | Yes | American odds for the over side. |
| `under_odds` | Yes | American odds for the under side. |
| `book` | No | Sportsbook or source label for diagnostics and breakdowns. |
| `game_id` | No | Stable game identifier if known. |
| `recent_team` | No | Player team context at replay time. |
| `opponent_team` | No | Optional opponent field; normalized with `opp_team`. |
| `opp_team` | No | Optional opponent field alias; normalized with `opponent_team`. |
| `market_source` | No | Source label for the local historical prop row. |
| `pulled_at` | No | Timestamp for the source snapshot when available. |

### `v0.4.4` Reporting And Diagnostics

Goal: make Step 4 results reviewable from generated artifacts instead of requiring raw CSV inspection.

Completion signal: replay outputs provide stable machine-readable and Markdown summaries with reconciled singles, parlays, and skip-accounting breakdowns.

Artifacts to update:

- replay summary JSON
- replay summary Markdown
- diagnostic breakdown JSON or CSV outputs
- reporting tests

- [x] Expand replay outputs beyond one summary number.
- [x] Add summary breakdowns by season.
- [x] Add summary breakdowns by week.
- [x] Add summary breakdowns by stat.
- [x] Add summary breakdowns by book.
- [x] Add summary breakdowns by selected side.
- [x] Add summary breakdowns by edge bucket.
- [x] Add explicit counts for skipped rows due to unsupported stat.
- [x] Add explicit counts for skipped rows due to missing odds.
- [x] Add explicit counts for skipped rows due to missing actual outcome.
- [x] Add explicit counts for skipped rows due to no selection because the edge threshold was not met.
- [x] Save both machine-readable and Markdown artifacts for the new breakdowns.
- [x] Keep the top-parlay section, but clearly separate singles results from parlay results.

### `v0.4.5` Selection Policy And Parlay Rules

Goal: make the replay policy explicit, configurable, and reviewable instead of relying on implicit defaults.

Completion signal: every replay artifact can be traced back to a known selection policy, stake configuration, and parlay rule set.

Artifacts to update:

- `docs/Step4Plan.md`
- replay CLI help or docs
- policy tests
- replay reports

- [x] Make replay selection policy explicit and configurable.
- [x] Track the default `min_edge` in this document.
- [x] Track the default stake size in this document.
- [x] Keep singles evaluated separately from parlays.
- [x] Keep same-game penalty and same-team penalty as conservative defaults unless changed deliberately.
- [x] Add optional caps for `max picks per week`.
- [x] Add optional caps for `max picks per player`.
- [x] Add optional caps for `max picks per game`.
- [x] Add baseline comparisons for no-threshold selection.
- [x] Add baseline comparisons for top-edge-only selection.
- [x] Add baseline comparisons for singles-only versus singles-plus-parlays.

Current policy defaults to lock during Step 4 hardening:

- `min_edge`: `0.05`
- `stake`: `1.0`
- singles and parlays: reported separately
- same-game penalty: `0.97`
- same-team penalty: `0.985`

### `v0.4.6` Full Replay Runs And Documentation

Goal: produce the full historical replay evidence package for 2024, 2025, and combined reporting.

Completion signal: finalized replay runs exist for both seasons and combined outputs, with stable docs artifacts and a short written interpretation for each report set.

Artifacts to update:

- season replay outputs under `docs/`
- combined replay comparison outputs under `docs/`
- `VERSIONS.md`

- [x] Run the finalized replay flow on the 2024 local historical props file.
- [x] Run the finalized replay flow on the 2025 local historical props file.
- [x] Save stable docs artifacts for each year.
- [x] Save a combined comparison artifact across both years.
- [x] Summarize total bets.
- [x] Summarize win, loss, and push counts.
- [x] Summarize staked units.
- [x] Summarize profit units.
- [x] Summarize ROI.
- [x] Summarize win rate.
- [x] Summarize best and worst stats.
- [x] Summarize best and worst books when book data exists.
- [x] Add a short interpretation section explaining whether the result looks usable, noisy, or clearly not ready.

#### v0.4.6 Replay Results Summary

Props source: `docs/synthetic_replay_props.csv` — lines derived from each player's 4-game shifted trailing average, rounded to floor+0.5. This is a trend-baseline substitute for real historical closing lines.

| Season | Bets | Wins | Losses | ROI | Win Rate |
| --- | --- | --- | --- | --- | --- |
| 2024 | 16,935 | 9,739 | 7,196 | +9.8% | 57.5% |
| 2025 | ~19,425 | — | — | — | — |
| Combined | 36,360 | — | — | +5.9% | 55.5% |

Best stat (2024): `receiving_tds` ROI +51.3%. Worst stat (2024): `carries` ROI -16.5%.

#### v0.4.6 Interpretation

Engineering gate is closed. The pipeline runs reproducibly on 41,508 synthetic props rows and emits the full artifact set across both seasons and combined.

**The ROI here is not a strategy verdict.** Lines were generated from the same nflverse data used to train the models, so the model has a structural advantage over the baseline (it sees EPA, opponent context, and shrinkage signals that the naive trailing average ignores). A positive ROI confirms the model adds signal beyond trend-following; it does not confirm profitability against real sportsbook lines.

Strategy gate remains open pending real historical closing lines (reserved for Step 6 when live Odds API ingestion begins).

### `v0.4.7` Step 4 Closeout And Step 5 Handoff

Goal: stop treating replay as exploratory output and freeze it as a dependable upstream contract for the app layer.

Completion signal: Step 4 outputs and interfaces are stable enough that Step 5 consumers can build against them without redefining shapes.

Artifacts to update:

- `docs/Step4Plan.md`
- `docs/plan.md` if Step 4 wording still needs to reflect local-replay-first reality
- `VERSIONS.md`
- API or UI handoff notes

- [x] Freeze the replay artifact contract so the UI and API layer can depend on it.
- [x] Add a short handoff section in this document naming the outputs Step 5 will consume.
- [x] Update `docs/plan.md` only if the Step 4 completion language still needs correction.
- [x] Update `VERSIONS.md` with the final Step 4 checkpoint entry.

#### Frozen Contract

The following artifact shapes are stable for Step 5 consumers. Do not change field names or file naming patterns without bumping the contract version.

| Artifact | Path pattern | Consumed by |
| --- | --- | --- |
| Picks CSV | `docs/paper_trade_picks_{label}.csv` | `api/services/replay_service.py` |
| Picks JSON | `docs/paper_trade_picks_{label}.json` | API |
| Parlays CSV | `docs/paper_trade_parlays_{label}.csv` | API |
| Summary JSON | `docs/paper_trade_summary_{label}.json` | `replay_service.load_replay_artifacts()` |
| Summary Markdown | `docs/paper_trade_summary_{label}.md` | human review |
| Breakdown CSVs/JSONs | `docs/paper_trade_breakdown_by_{dim}_{label}.{ext}` | `build_replay_summary_response()` |

Seed props file consumed by `/api/slate` cold-start: `docs/synthetic_replay_props.csv` (set in `api/settings.py:sample_props_path`).

`api/schemas.py:SlateResponse` and `ReplaySummaryResponse` are the Pydantic contracts Step 5 builds against. These are frozen as of v0.4.7.

## Public Interfaces And Contracts To Lock

The local props replay schema should be documented exactly once in this file and reused everywhere else.

Replay CLI contract to stabilize during Step 4:

- `--props-file`
- `--train-years`
- `--replay-years`
- `--min-edge`
- `--stake`
- `--out-dir`
- `--weeks`
- `--stats`
- `--books`

Replay output contract to stabilize during Step 4:

- picks CSV
- parlays CSV
- summary JSON
- summary Markdown
- breakdown JSON or CSV for week, stat, and book diagnostics

Future live-season odds ingestion should normalize into the same shape as the local replay schema so Step 6 can swap data sources without changing replay consumers.

Calibration integration remains a nullable dependency. Replay must accept both of these modes through the same pricing path:

- no calibrator
- saved calibrator path

## Framework For The Next Few Steps

### Step 5

Step 5 should consume frozen Step 4 outputs and contracts rather than inventing new shapes in the UI layer.

- `v0.5a` should expose read-only Python-side endpoints for health, slate or replay summary, and model-backed prop evaluation using the Step 4 artifact contract as the starting point.
- `v0.5b` should add player detail, prop table, and parlay builder views on top of the same stable replay and evaluation structures.
- `v0.5c` should layer on the LLM analyst, weather, injuries, and accessibility only after the Python-side interfaces are stable.

### Step 6

Step 6 should replace local replay only with live preseason execution using The Odds API as the live odds source.

- The live pipeline should normalize incoming odds into the same schema used by Step 4 replay.
- Add stale-data detection, cache visibility, and failure reporting here, not during Step 4.

### Step 7

Step 7 should focus on automation and operational confidence, not core data-shape redesign.

The live run should be able to produce:

- slate
- player projections
- prop evaluations
- parlay suggestions
- LLM summary

Any missing live-data or stale-data edge cases found in preseason should already have owners from Step 6.

## Test Plan

Unit coverage for replay validation:

- unsupported stat rejected
- missing required columns rejected
- opponent field normalization works
- skipped-row accounting is correct

Unit coverage for selection policy:

- edge threshold behavior
- max-per-week, max-per-player, and max-per-game caps
- singles and parlays reported separately

Integration coverage for replay:

- one-week sample replay
- one-season replay
- two-season combined replay
- replay with and without calibrator

Reporting checks:

- all expected output files are written
- summary counts reconcile with pick rows
- per-week and per-stat breakdown totals reconcile with overall totals

Acceptance scenario for Step 4 closeout:

- run replay from a local props file
- produce docs artifacts
- inspect ROI and breakdowns
- confirm outputs are stable enough to serve Step 5 consumers

## Assumptions And Defaults

- `docs/plan.md` remains the macro source of truth; `docs/Step4Plan.md` is the supplementary active tracker.
- The Odds API is reserved for live-season odds usage, not historical model training.
- Step 4 completion is based on local historical replay now, not historical Odds API access.
- Step 3 calibration is optional during Step 4 and should improve replay when available, but must not block replay execution.
- Versioning stays on `v0.4.y` for any Step 4 sub-updates, including Step 2 bug fixes discovered while Step 4 is active.
