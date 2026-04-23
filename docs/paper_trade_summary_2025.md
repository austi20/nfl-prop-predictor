# Paper Trade Replay 2025

Replay years: 2025
Minimum edge: 0.050
Stake per bet: 1.00 units

## Validation

- Input rows: 41508
- Rows after filters: 20947
- Rows priced: 20947
- Selected rows: 18407
- Skipped unsupported stat: 0
- Skipped missing odds: 0
- Skipped missing actual outcome: 0
- No selection because edge threshold not met: 2540

## Singles

- Bets: 18407
- Wins: 10175
- Losses: 8232
- Pushes: 0
- Profit: 1018.000 units
- ROI: 5.531%
- Win rate: 55.278%

## Parlays

- Candidates: 20
- Wins: 20
- Losses: 0
- Pushes: 0
- Profit: 52.893 units
- ROI: 264.463%
- Average expected value: 2.645 units

## Baselines

- Current policy singles ROI: 5.531%
- No-threshold singles ROI: 5.067%
- Top-edge-only singles ROI: 21.488%
- Singles plus top parlay per week ROI: 5.587%

## Diagnostics

- Best stat: `receiving_tds` (ROI=51.718%, profit=1075.727)
- Worst stat: `carries` (ROI=-21.169%, profit=-589.545)
- Best book: `synthetic` (ROI=5.531%, profit=1018.000)
- Worst book: `synthetic` (ROI=5.531%, profit=1018.000)

## Weekly Breakdown

| season | week | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025 | 1 | 930.000 | 540.000 | 390.000 | 0.000 | 930.000 | 100.909 | 10.85% | 58.06% |
| 2025 | 2 | 924.000 | 515.000 | 409.000 | 0.000 | 924.000 | 59.182 | 6.40% | 55.74% |
| 2025 | 3 | 927.000 | 540.000 | 387.000 | 0.000 | 927.000 | 103.909 | 11.21% | 58.25% |
| 2025 | 4 | 1048.000 | 562.000 | 486.000 | 0.000 | 1048.000 | 24.909 | 2.38% | 53.63% |
| 2025 | 5 | 949.000 | 493.000 | 456.000 | 0.000 | 949.000 | -7.818 | -0.82% | 51.95% |
| 2025 | 6 | 977.000 | 552.000 | 425.000 | 0.000 | 977.000 | 76.818 | 7.86% | 56.50% |
| 2025 | 7 | 999.000 | 524.000 | 475.000 | 0.000 | 999.000 | 1.364 | 0.14% | 52.45% |
| 2025 | 8 | 854.000 | 464.000 | 390.000 | 0.000 | 854.000 | 31.818 | 3.73% | 54.33% |
| 2025 | 9 | 921.000 | 505.000 | 416.000 | 0.000 | 921.000 | 43.091 | 4.68% | 54.83% |
| 2025 | 10 | 953.000 | 487.000 | 466.000 | 0.000 | 953.000 | -23.273 | -2.44% | 51.10% |
| 2025 | 11 | 977.000 | 556.000 | 421.000 | 0.000 | 977.000 | 84.455 | 8.64% | 56.91% |
| 2025 | 12 | 912.000 | 512.000 | 400.000 | 0.000 | 912.000 | 65.455 | 7.18% | 56.14% |

## Stat Breakdown

| stat | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| receiving_tds | 2080.000 | 1653.000 | 427.000 | 0.000 | 2080.000 | 1075.727 | 51.72% | 79.47% |
| rushing_tds | 1024.000 | 785.000 | 239.000 | 0.000 | 1024.000 | 474.636 | 46.35% | 76.66% |
| receiving_yards | 3922.000 | 2125.000 | 1797.000 | 0.000 | 3922.000 | 134.818 | 3.44% | 54.18% |
| interceptions | 523.000 | 343.000 | 180.000 | 0.000 | 523.000 | 131.818 | 25.20% | 65.58% |
| passing_tds | 611.000 | 378.000 | 233.000 | 0.000 | 611.000 | 110.636 | 18.11% | 61.87% |
| completions | 478.000 | 283.000 | 195.000 | 0.000 | 478.000 | 62.273 | 13.03% | 59.21% |
| passing_yards | 469.000 | 277.000 | 192.000 | 0.000 | 469.000 | 59.818 | 12.75% | 59.06% |
| receptions | 4131.000 | 2168.000 | 1963.000 | 0.000 | 4131.000 | 7.909 | 0.19% | 52.48% |
| rushing_yards | 2384.000 | 1013.000 | 1371.000 | 0.000 | 2384.000 | -450.091 | -18.88% | 42.49% |
| carries | 2785.000 | 1150.000 | 1635.000 | 0.000 | 2785.000 | -589.545 | -21.17% | 41.29% |

## Book Breakdown

| book | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic | 18407.000 | 10175.000 | 8232.000 | 0.000 | 18407.000 | 1018.000 | 5.53% | 55.28% |

## Interpretation

Result looks usable enough to keep moving, with positive replay economics after vig on this slice. It still deserves stress checks across seasons, books, and edge buckets before relying on it.

## Top Parlays

- 2025 Week 2: `00-0038416 passing_yards over | 00-0036223 carries under` (EV=2.645, joint_prob=1.000, result=win)
- 2025 Week 18: `00-0033319 passing_yards over | 00-0038582 completions over` (EV=2.645, joint_prob=1.000, result=win)
- 2025 Week 14: `00-0038102 passing_yards over | 00-0033319 completions over` (EV=2.645, joint_prob=1.000, result=win)
- 2025 Week 2: `00-0036223 carries under | 00-0038416 completions over` (EV=2.645, joint_prob=1.000, result=win)
- 2025 Week 18: `00-0033319 passing_yards over | 00-0033869 completions over` (EV=2.645, joint_prob=1.000, result=win)
