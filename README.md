# NFL Fantasy Projection Model

Does a fitted projection model beat just averaging a player's recent scores?

On 2,741 player weeks from 2025, barely. The model misses by 4.66 fantasy points on average (full PPR). A season to date average misses by 4.78. That is 0.12 points, about 2.5%. The model's edge is clearer in ranking: rank correlation 0.637 against 0.590.

## Baselines

Same 2,741 player weeks for every row (700 each of RB, WR, TE and 641 QB, weeks 2 to 18, players with at least 3 career games). MAE and Spearman rank correlation are computed per position, then averaged with equal weight.

| method | MAE | rank correlation | start/sit pair accuracy |
|---|---|---|---|
| model | 4.66 | 0.637 | 73.5% |
| trailing 4 game average | 4.89 | 0.584 | 71.6% |
| season to date average | 4.78 | 0.590 | 71.9% |

Start/sit pair accuracy: take every two players at the same position in the same week and ask whether the one projected higher actually scored more. The model picks right in 73.5% of pairs, about 2 points better than either average.

Practical read: in a toss up between two same position players, the model picks the better one roughly 3 times in 4, and a plain average does it about 5 times in 7. Real, small, and nowhere near enough to call a week.

## Floor and ceiling band

The app shows a floor (10th percentile) and a ceiling (90th percentile), so the band should hold 80% of outcomes. It holds 61.8%.

| position | actual outcomes inside the band |
|---|---|
| QB | 67.6% |
| RB | 61.0% |
| WR | 59.0% |
| TE | 60.0% |
| all | 61.8% |

The band is too narrow at every position. I have not widened it yet. The band here is a lognormal with the model's projected mean and the per player spread the app ships (`eval/fantasy_spread.py`), not the app's 5,000 draw simulation, so treat the number as close, not exact. Using the cruder spread from the backtest cache gives 60.2%.

## Numbers I did not carry forward

An earlier calibration sweep (`docs/fantasy_calibration_sweep.md`) reports MAE 4.99 and rank correlation 0.595. Those belong to the tuning run before the depth chart and rookie work. The shipped calibration scores 4.66 and 0.637 on the same rows, and that is what the table uses.

## How it works

Per position models (QB, RB, WR/TE) predict each stat. Those predictions are blended with the player's trailing form, adjusted for the opponent, injuries and depth chart role, then converted to fantasy points. The sweep that tunes the blend lives in `eval/fantasy_calibration.py`.

## Data

nflverse weekly player stats, 2015 through 2025, loaded through `data/nflverse_loader.py`. Actual fantasy points are recomputed from the raw stat columns with full PPR weights.

## Run it

```
uv run python scripts/baseline_comparison.py
```

It reads `cache/fantasy_eval_cache_2025.pkl`. If that file is missing or stale, rebuild it:

```
uv run python -c "from eval.fantasy_calibration import build_eval_cache; print(build_eval_cache(2025))"
```

## What would break this

- The tuning sweep and this table use the same 2025 rows. The calibration was tuned on them, so the model's numbers are somewhat flattering. The baselines have no tuned parameters.
- 90 of the 2,741 rows had no usable history for a baseline (a first game back, or none this season). Those rows use the model's own projection as the baseline, which makes the baselines look slightly better than they are.
- The sample is 2025 only. One season is a single draw, and a 0.12 point gap in MAE is inside what a different sample could move.
- No confidence intervals on the gaps yet.

## What I would do next

Bootstrap the MAE and rank gaps so I know whether 0.12 points is distinguishable from zero. Widen the band until it covers 80% and check it holds out of sample.
