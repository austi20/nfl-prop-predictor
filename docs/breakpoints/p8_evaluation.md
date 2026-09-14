# Breakpoint Evaluation — Phase P8: player role context (depth chart, rookies)

**Phase:** P8
**Author:** gunnar
**Date:** 2026-09-13
**Spec:** `docs/superpowers/specs/2026-09-13-player-context-role-and-market-anchoring-design.md`
**Plan:** `docs/superpowers/plans/2026-09-13-depth-chart-rank-and-rookies.md`

This document is Layer B of the testing requirement defined in
`docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md` §5 P3.
It is a merge gate, not optional.

Gated paths touched by this phase: `eval/fantasy_calibration.py` (three new
knobs: `depth_chart_damping`, `role_change_retention`, `rookie_cv_inflation`).

## 0. Why this phase needs a careful Layer B

A previous role-change attempt was **rejected in review** for re-introducing 30x
ratios between a projection and the player's own trailing average, and for making
Week-1 aggregate realism worse. Every correction here is therefore multiplicative,
clamped, and derived from measured baselines rather than hand-picked constants.
Section 1 exists specifically to prove the runaway cannot recur.

## 1. Boundary probes

Evidence below is the recorded output of the probe script in §6.

### `depth_chart.bucket(rank, position)`

| Input rank | RB / WR | QB / TE | Note |
|---|---|---|---|
| `None` | `None` | `None` | no chart -> caller falls back to position-wide |
| `0` | `None` | `None` | invalid rank rejected, not coerced to 1 |
| `1` | 1 | 1 | |
| `2` | 2 | 2 | |
| `3` | 3 | 2 | QB/TE collapse at 2 |
| `4` | 3 | 2 | saturates |
| `99` | 3 | 2 | saturates, no overflow |

Buckets cap at 3 because the legacy (2015-2024) `depth_team` column never exceeds
3. Capping keeps the two upstream schema eras comparable.

### `_depth_chart_factor` multiplier under extreme baseline ratios

| old bucket baseline | new bucket baseline | ratio | Observed multiplier | Applied |
|---|---|---|---|---|
| 1.0 | 1000.0 | 1000x | **1.22** | yes |
| 1000.0 | 1.0 | 0.001x | **0.78** | yes |
| 0.0 | 50.0 | undefined | 1.0 | no |
| 50.0 | 0.0 | undefined | 1.0 | no |

Clamp band is `(context_clamp_lo, context_clamp_hi) = (0.78, 1.22)`.
**A 1000x baseline ratio produces a 1.22x multiplier.** The 30x runaway is
structurally unreachable through this path. A zero baseline on either side
returns neutral rather than dividing by zero.

### `_role_retention(current_bucket, prior_bucket, calib)`

| Bucket delta | Observed retention | Effect on `form_weight` at n=8 |
|---|---|---|
| 0 (unmoved) | **1.0** | 8/12 = 0.667 — identical to pre-phase behavior |
| 1 | 0.45 | 3.6/7.6 = 0.474 |
| 2 | 0.2025 | 1.62/5.62 = 0.288 |
| either rank `None` | **1.0** | identical to pre-phase behavior |

The `delta == 0` and `rank is None` rows are the important ones: every player
whose slot did not move, and every player with no depth-chart coverage, takes a
numerically identical path to the previous release.

### `draft.capital_multiplier(capital)`

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ | UDFA (`None`) |
|---|---|---|---|---|---|---|---|---|---|
| Observed | 1.15 | 1.08 | 1.02 | 0.97 | 0.93 | 0.90 | 0.88 | 0.85 | 0.85 |

Monotone decreasing, bounded `[0.85, 1.15]`. Round 8 does not exist in the modern
draft; it falls through to the undrafted value rather than raising.

## 2. Outlier injection

| Scenario | Input | Expected | Observed | Evidence |
|---|---|---|---|---|
| Empty depth frame | `pd.DataFrame()` | 0 rows, no raise | 0 rows | §6 probe |
| Depth frame missing every expected column | `DataFrame({'x':[1]})` | 0 rows, no raise | 0 rows | §6 probe |
| Depth chart present, weekly stats absent for player | rookie path | baseline x capital, widened cv | `mean == 95.0 * 1.15`, `std > yard_cv * mean` | `tests/test_fantasy_service_depth.py::test_rookie_with_no_history_uses_rank_baseline_and_widens_spread` |
| Player on no depth chart at all | `current_rank -> None` | position-wide baseline, retention 1.0 | confirmed | `tests/test_depth_chart.py::test_unknown_player_returns_none` |
| Rank bucket with no baseline rows | unseen `(pos, bucket, stat)` | fall back to position-wide | confirmed | `tests/test_fantasy_service_depth.py::test_baseline_lookup_prefers_exact_bucket` |
| Multiple same-week snapshots | two snapshots, same NFL week | last one wins | rank 1 (later) beats rank 2 | `tests/test_depth_chart.py::test_normalize_modern_collapses_same_week_snapshots_to_the_last` |
| Stale preseason snapshot vs in-season | Aug snapshot RB3, Sep snapshot RB1 | both retained, dated | weeks `[0, 1]`, ranks `[3, 1]` | `tests/test_depth_chart.py::test_normalize_modern_keeps_history_and_dates_each_snapshot` |

## 3. Exception paths

| Failure mode | Trigger | Expected recovery | Observed |
|---|---|---|---|
| Unpublished season 404 | `load_depth_charts([2027])` | skip that season, keep the rest | `rank_frame` try/except per season, continues |
| nflverse schema change | neither `pos_rank` nor `depth_team` present | empty frame -> position-wide baselines | `_normalize_*` return `_empty()` |
| Depth-chart import raises inside the projector | any exception | `(None, None)` ranks, pre-phase behavior | `_depth_ranks_for` try/except |
| Depth-chart import raises inside the slate | any exception | `rank=None, capital=1.0` | `_compute_slate` try/except around lookup |
| Draft-pick file unavailable | `load_draft_picks` raises | empty frame -> multiplier 1.0 | `_picks_frame` returns empty columns |
| Schedule unavailable for week derivation | `load_schedules` raises | all snapshots -> week 0 | `_week_starts` returns `()`, `_assign_week` returns 0 |
| Calibration artifact predates the new keys | load `models/fantasy_calibration.json` | defaults fill in, old board preserved | `0.5 / 1.35 / 1.0` returned — verified |

Every one of these degrades to the pre-phase projection rather than failing the
request. Depth-chart data is an enhancement, never a gate.

## 4. Hypothetical failure modes

**"The depth chart is silently stale."**
The modern feed is a daily ESPN snapshot; if the publisher freezes, `current_rank`
keeps returning the last good chart with no error. Detection: `rank_frame`
carries an `asof` timestamp per row, so a staleness check is a max() away.
Not yet monitored — accepted risk for this phase, noted for the next.

**"Legacy ranks are scraped listings, not real workload."**
A listed RB1 in 2015-2024 is not always the workload leader, which would wash out
the bucket baselines. Measured instead of assumed:

| position / stat | bucket 1 | bucket 2 | bucket 3 | position-wide |
|---|---|---|---|---|
| RB rushing_yards | 57.7 | 27.1 | 14.1 | 32.8 |
| RB receptions | 2.5 | 1.7 | 0.9 | 1.7 |
| WR receiving_yards | 52.6 | 23.5 | 14.1 | 34.5 |
| QB passing_yards | 238.4 | 100.4 | — | 205.4 |
| TE receptions | 3.2 | 1.4 | — | 2.2 |

Separation is clean and monotone at every position. The risk did not materialize;
the fallback to touch-share-derived rank described in the spec is not needed.

**"Only 30% of weekly rows join to a rank, so the buckets are a biased subsample."**
Measured: 60,502 of 201,058 weekly rows match (30.1%). The gap is structural — a
depth chart lists ~3 players per position per team while the weekly frame contains
everyone who took a snap. The matched subsample is 60k rows and the resulting
baselines are monotone, so the estimate is sound. Unmatched rows still contribute
to the position-wide fallback baseline.

**"A promotion double-counts against the usage trend."**
`_resolve_role_precedence` stands `usage_trend` down whenever `depth_chart`
applies. Verified live: Tuten shows `depth_chart` applied and `usage_trend`
neutralized with reason "Role move already priced by the depth chart —
superseded"; Travis Hunter (no bucket change) keeps `usage_trend` applied.

**"The correction overshoots and a backup projects like a star."**
Three independent bounds: the factor clamps to `[0.78, 1.22]`; the trailing mean
clamps to `[0.45, 1.7] x anchor`; and retention can only move weight *toward* the
rank-conditioned baseline, never past it. A promoted player's ceiling is the
average starter at his slot, which is the honest prior. Regression guard:
`scripts/verify_role_context.py`.

## 5. Sign-off

Observed behavior change on the live 2026 Week-2 board:

| player | before | after | mechanism |
|---|---|---|---|
| Bhayshul Tuten (RB2 -> RB1) | 9.63 | **11.37** | depth_chart x1.1369 + retention 0.45 |
| Travis Hunter (WR6 -> WR4, same bucket) | 5.69 | 5.69 | unchanged, `usage_trend` retained |
| Travis Etienne | — | 16.23 | unmoved slot, pre-phase path |

Aggregate gate: `scripts/verify_fantasy_calibration.py` — see §6.

## 6. Reproducing the probes

```bash
uv run pytest tests/test_depth_chart.py tests/test_draft.py \
              tests/test_fantasy_service_depth.py tests/test_fantasy_slate_service.py -q
uv run python scripts/verify_fantasy_calibration.py
uv run python scripts/verify_role_context.py --season 2026 --week 2
```
