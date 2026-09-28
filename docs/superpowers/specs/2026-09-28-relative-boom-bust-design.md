# Relative Boom/Bust: Design

**Date:** 2026-09-28
**Status:** approved (the user delegated every choice to the recommended option)

## Problem

Boom and bust are hard set per position: a WR booms at 20+ PPR points and busts at 7 or less, whatever his projection. So boom is mostly a restatement of the projection. A WR projected at 6 almost never "booms" even when he triples his projection, and a star at 22 "booms" whenever he merely meets it. It also ignores scoring mode: half PPR uses the PPR cutoffs.

The user's definition: boom is the chance a player overshoots **his own projection** by a meaningful margin, and bust is the chance he falls well short of it. The chance should come from that player's own sampling distribution, so a volatile player gets more of both than a steady one at the same projection.

## Decision

- **Boom** = P(points >= 1.5 x projection). **Bust** = P(points <= 0.5 x projection).
- Probabilities are read from the same Monte Carlo samples the app already draws, after the per player spread rescale (`eval/fantasy_spread.py`). That sd is the "reasonable standard deviation": it is fit on real residuals and moves with the player's own recent volatility and touchdown reliance.
- The thresholds in points are returned and shown next to each percentage in the GUI ("boom 22% · 21.0+", "bust 25% · 7.0 or less").

### Why 1.5x and 0.5x

Measured on the locked 2025 backtest rows with projection >= 5: actual weeks at or above 1.5x projection run 14% (QB) to 26% (TE); at or below 0.5x run 25% to 29%. Both are frequent enough to mean something and rare enough to be a real boom or bust. 1.25x hits 28-34% (not a boom); 2.0x hits 4-12% (too rare to separate players). Rates fall as projection rises (QB 15+: 10% boom), so the percentages will vary across players on their own.

### Rejected

- **Quantile thresholds** (boom = above the player's own p80): every player gets exactly 20%. The user's literal reading, explicitly not wanted.
- **Projection plus a fixed point margin** (e.g. +7): a 5 point player almost never booms and a 25 point player always does. Same flaw as today.

## Scope

In:
- `eval/fantasy_points.py`: replace `POSITION_CUTOFFS` / `position_cutoffs` with `BOOM_MULTIPLIER = 1.5`, `BUST_MULTIPLIER = 0.5` and `relative_cutoffs(projected_points)`. The now unused `position` argument of `project_fantasy_points` is removed and its callers updated.
- `api/schemas.py` + `api/services/fantasy_slate_service.py`: the board row carries `boom_cutoff` and `bust_cutoff`.
- Desktop: `this-week-page.tsx` row and aria label, `player-card.tsx`, `types.ts`.
- `scripts/diag/boom_bust_drivers.py`: score its Brier check with the relative thresholds.
- New `scripts/diag/verify_boom_bust.py`: builds real 2025 boards through the live path and compares predicted vs actual boom/bust by position and projection bucket. Replaces `scripts/diag/verify_spread.py`, which scored the old cutoffs under a lognormal the app never used.

Out:
- Projection means, the trailing blend, context factors, market anchor, GLMs. Untouched, per the user.
- `models/fantasy_spread.json` coefficients. Refit only if the live path validation shows the relative definition is badly calibrated; otherwise reported as is.
- `eval/fantasy_calibration.py` tuner objective (`_BOOM` / `_BUST`). It tunes the projection knobs, which are locked; changing its objective would change what "locked" means.

## Edge cases

- Projection <= 0: cutoffs 0 and 0, boom 0, bust 1.
- `simulations <= 0` (degenerate path): boom 0, bust 0 (the projection sits between the cutoffs).
- Boom is inclusive (>=), bust inclusive (<=), as today.
- The slate cache is in memory only, so a sidecar restart serves the new fields. No migration.

## Testing

- `tests/test_fantasy_points.py`: cutoffs are 1.5x and 0.5x the projection; boom and bust equal the sample fractions; at the same projection a wider `total_sd` gives higher boom and higher bust; zero projection edge case; half PPR cutoffs follow the half PPR projection.
- `tests/test_fantasy_slate_service.py`: board rows carry both cutoffs.
- Desktop vitest: the This Week row renders the threshold next to each percentage.
- Live path validation (`verify_boom_bust.py`) reported in `VERSIONS.md`.
