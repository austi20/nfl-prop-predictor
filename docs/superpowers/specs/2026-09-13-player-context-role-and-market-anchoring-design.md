# Player context: role changes, rookies, and market anchoring

Date: 2026-09-13
Status: approved (design)

## Problem

The Week-N fantasy board projects players into the role they *had*, not the role
they *have*. Three distinct defects, one missing input.

### 1. Offseason role changes are invisible

`_trailing_fantasy_distributions` (`api/services/fantasy_service.py:244`) anchors
on a player's recency-weighted last-8 games, regressed toward a **position-wide**
baseline with weight `n/(n+4)`.

Bhayshul Tuten's last 8 games *are* RB3 touches behind Travis Etienne, and the
regression target is the mean of every RB in the league (itself ~RB3-shaped).
Both terms encode the old role. Nothing in the anchor knows he is now RB1.

Verified against live nflverse depth charts:

```
JAX, 2026 snapshot dt=2026-09-13T12:42:08Z
  Bhayshul Tuten        RB  pos_rank 1      <- 2025 preseason: pos_rank 3
  Chris Rodriguez Jr.   RB  pos_rank 2
```

### 2. The factor built for this cannot see it

`_usage_factor` (`fantasy_service.py:822`) reads `data/usage.usage_trend`, which
compares a player's last 3 games against games 4-8 back. That is a *within-season*
trend detector. An offseason depth-chart promotion produces no such trend, so the
factor returns neutral and the whole contexting phase no-ops on exactly the case
it was built for.

### 3. Rookies are absent or fabricated

With `n == 0` the trailing mean collapses to the position-wide baseline, so every
rookie projects as a generic league-average player at their position. Worse, the
slate pre-score (`api/services/fantasy_slate_service.py:103`) returns `0.0` when
`n < _MIN_TRAILING_GAMES`, so rookies sort last inside the per-team depth cap and
are cut from the board entirely.

### Missing input

**Depth-chart rank.** nflverse publishes it, it is fresh daily, and the repo has
no loader for it. Additionally, the Kalshi coin-flip line is a live, forward-looking
market estimate of the same quantity and is currently unused for player projections.

## Non-goals

- Re-touching the trailing anchor's shape or the shared GLM fits.
- Re-tuning locked `FantasyCalibration` values. New knobs get defaults that
  reproduce today's board when the new data is absent.
- Prop probability calibration (still deferred pending real quote capture).

## Prior art / constraint

A role-change trailing-anchor *fallback* was attempted and **rejected in review**:
it re-introduced 30x ratios and made Week-1 aggregate realism worse. Every
correction in this design is therefore multiplicative, bounded, and derived from
data rather than hand-picked, and the verification gate explicitly asserts a
bounded ratio against the trailing anchor.

---

## Design

### Correction precedence

Three mechanisms can correct a stat. They are **mutually exclusive per stat**,
highest priority wins, so a single role change is never counted twice:

| priority | mechanism | fires when |
|---|---|---|
| 1 | `market` | a Kalshi rung for that stat trades two-sided near a coin flip |
| 2 | `depth_chart` | current depth rank differs from the rank the trailing stats were earned at |
| 3 | `usage_trend` | neither of the above; existing within-season snap/air-yards trend |

Rationale: a priced market already integrates the depth chart, the injury report
and the beat news. Where one exists it is strictly better information. Where it
does not -- which is most of the board, see coverage below -- the depth chart is
the best available prior.

### Phase 1 - Depth-chart data layer

`load_depth_charts(years)` in `data/nflverse_loader.py`, following the existing
`_load_or_fetch` parquet-cache pattern used by `load_snap_counts`.

`data/depth_chart.py` normalizes two incompatible upstream schemas into one frame
`(gsis_id, season, week, team, position, rank)`:

| era | shape | rank column | position column |
|---|---|---|---|
| 2015-2024 | weekly rows, 15 cols | `depth_team` | `depth_position` |
| 2025-2026 | daily ESPN snapshots, 12 cols | `pos_rank` | `pos_abb` |

Public surface:

- `rank_frame(seasons)` -- the normalized join table
- `current_rank(gsis_id, season, week)` -- latest snapshot at or before the request
- `prior_rank(gsis_id, season, week)` -- modal rank across the trailing-8 window,
  i.e. *the rank at which the trailing stats were actually earned*

`prior_rank` is the piece that makes this work: comparing current rank against the
rank the anchor encodes is what isolates a role change from a role that never moved.

### Phase 2 - Rank-conditioned baselines

`_baselines_for` re-keys from `(position, stat)` to `(position, rank_bucket, stat)`.
Buckets mirror the existing `_DEPTH_BY_POSITION` roster shape:

```
QB {1, 2+}   RB {1, 2, 3+}   WR {1, 2, 3, 4+}   TE {1, 2+}
```

Built by joining the historical weekly rank frame (2015-2024 carries true weekly
ranks) onto `weekly`.

**Fallback chain: exact bucket -> position-wide -> 0.0.** If the join fails for any
season the result is byte-identical to today's behavior. This is the safety property
that matters given the prior rejected attempt.

`_trailing_fantasy_distributions` gains a `depth_rank` argument and uses the
bucketed baseline as both the regression target and the `anchor` floor. Tuten's
anchor still uses his real RB3 games; it simply regresses toward the RB1 archetype
instead of the all-RB mean.

### Phase 3 - `_depth_chart_factor`

Fires on `current_rank != prior_rank`. The multiplier is **derived from the ratio
between the two rank buckets' own baselines** (RB1 baseline FP / RB3 baseline FP),
damped by a `FantasyCalibration` strength and clamped to the existing factor band.

Deriving the magnitude from the baselines rather than a hand-picked constant is
what prevents the 30x failure mode: the correction can never exceed the empirical
gap between the two roles.

Suppresses `usage_trend` when it fires (see precedence table).

### Phase 4 - Rookies

`data/draft.py` exposes `draft_capital(gsis_id) -> (round, pick) | None` from
`import_draft_picks` (verified: 2026 class present).

- `n == 0` in `_trailing_fantasy_distributions`: mean = rank-conditioned baseline
  scaled by a draft-capital adjustment (R1 up, R6/UDFA down), clamped; `cv`
  inflated by a calibration knob so floor/ceiling honestly widen.
- Slate `_prescore`: when `n < _MIN_TRAILING_GAMES`, return that same figure
  instead of `0.0`, so rookies rank sensibly inside the per-team depth cap.
- No schema change. The factor's `reason` string carries the provenance
  ("Rookie, no NFL history -- projected from RB1 depth slot and Round 2 draft
  capital") and renders in the existing player card.

### Phase 5 - Market anchoring

`api/services/prop_board_service.py` already contains the machinery: `_coinflip_rung`
picks the rung whose yes-mid is nearest 50c inside a `(0.30, 0.70)` band on a book
no wider than `_MAX_SPREAD`. Verified live against `KXNFLRSHYDS-26SEP14DENKC`:
45/45 rungs priced, coin-flip rung resolved to "Patrick Mahomes: 15+".

New `_market_factor`:

1. Resolve the coin-flip rung for `(player, stat, game)`.
2. The strike is the market's implied **median**, not its mean. Convert using the
   model's own distribution shape: `implied_mean = (strike + 0.5) * (model_mean / model_median)`.
   This matters for skewed count stats (TDs) where median and mean diverge sharply.
3. Multiplier = `clamp(implied_mean / model_mean, lo, hi)`, damped by a calibration
   strength.

Best-effort by construction. Coverage measured today: 6 of 16 games carry rushing-yard
ladders, and only markets with `status == "active"` are priced. Absent market -> fall
through to the depth-chart prior.

### Phase 6 - Live bug: game-line inversion is dead

`kalshi_odds_service._mid_yes_prob` reads the integer-cent fields `yes_bid`,
`yes_ask`, `last_price`. The Kalshi API now returns `yes_bid_dollars`,
`yes_ask_dollars`, `last_price_dollars`. Measured against a live active event:

```
prop_board  _rung_mid_prices  non-None: 45/45   (handles _dollars)
kalshi_odds _mid_yes_prob     non-None:  0/45   (does not)
```

`nfl_game_lines()` therefore returns nothing, the implied-total override never
fires, and `_game_script_factors` has been silently falling back to schedule totals
in every request. Fix `_mid_yes_prob` to read `*_dollars` with the integer-cent
path retained as fallback, mirroring `prop_board_service._price_dollars`.

This is in scope because the user explicitly asked for Vegas lines to drive
multipliers, and this is the code path that reads them.

### Phase 7 - Full stat coverage

The per-position GLM targets cover a subset of what each position does:

| position | fitted today | missing |
|---|---|---|
| QB | passing_yards, passing_tds, interceptions, completions | **attempts, rushing_yards, carries, rushing_tds** |
| RB | rushing_yards, carries, rushing_tds | **receptions, receiving_yards, receiving_tds, targets** |
| WR/TE | receptions, receiving_yards, receiving_tds | **targets**, and for WR **rushing_yards, carries, rushing_tds** |

A pass-catching RB having no receiving GLM is the same class of defect as the role
blindness above: the model structurally cannot express part of the player's job.

Target matrix after this change:

| position | stats |
|---|---|
| QB | passing_yards, passing_tds, interceptions, completions, attempts, rushing_yards, carries, rushing_tds |
| RB | rushing_yards, carries, rushing_tds, receptions, receiving_yards, receiving_tds, targets |
| WR | receptions, receiving_yards, receiving_tds, targets, rushing_yards, carries, rushing_tds |
| TE | receptions, receiving_yards, receiving_tds, targets |

All eight are present in the nflverse weekly frame (verified).

Kalshi series map gains two live series found unmapped during discovery:

- `KXNFLPASSATT` -> `attempts`
- `KXNFLTD` -> anytime touchdown, a **derived** probability
  `P(rushing_tds + receiving_tds >= 1)` read off the existing Monte Carlo rather
  than a new GLM target.

Series probed and confirmed empty upstream (no markets listed): `KXNFLINT`,
`KXNFLRSHTDS`, `KXNFLRECTDS`, `KXNFLTGT`, `KXNFLANYTD`. Not mapped.

---

## Verification

1. **Aggregate gate.** `scripts/verify_fantasy_calibration.py` on the existing
   2741-row 2025 backtest. Position-balanced MAE, |bias| and rank correlation must
   not regress against the locked v0.9-m3.5 numbers (MAE 4.99, |bias| 0.27,
   rank 0.595).
2. **Bounded-ratio assertion.** New 2026 spot-check script asserting every
   projection stays inside a bounded ratio of its trailing anchor -- the explicit
   guard the rejected attempt lacked -- plus named review of Tuten, Travis Hunter
   and other known promotions.
3. **Unit tests.** Both-schema depth-chart normalizer; bucket fallback to
   position-wide; market > depth_chart > usage_trend precedence and mutual
   exclusion; rookie path; `_mid_yes_prob` against the `*_dollars` schema; the
   expanded stat matrix.

## Risks

- **Legacy depth charts are noisy.** 2015-2024 ranks are scraped preseason/weekly
  listings; a listed RB1 is not always the workload leader. The rank-conditioned
  baselines will be directionally right but blunt. If the backtest shows them too
  noisy to help, the fallback is deriving historical rank from realized
  team-position touch share instead. Decision point is gate 1.
- **Admitting rookies puts genuinely uncertain numbers on the board.** The widened
  spread is what keeps that honest; it is not optional.
- **Expanding GLM targets lengthens model fit time**, which is already ~11.6s per
  process and is paid per slate worker. Measure after Phase 7; if it regresses the
  slate build materially, fit the added targets lazily on demand.
