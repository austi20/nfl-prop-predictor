# Paper Trade Replay 2025

Replay years: 2025
Minimum edge: 0.050
Stake per bet: 1.00 units

## Validation

- Input rows: 144562
- Rows after filters: 21108
- Rows priced: 21108
- Selected rows: 18801
- Skipped unsupported stat: 0
- Skipped missing odds: 0
- Skipped missing actual outcome: 0
- No selection because edge threshold not met: 2307

## Singles

- Bets: 18801
- Wins: 10600
- Losses: 8201
- Pushes: 0
- Profit: 1435.364 units
- ROI: 7.635%
- Win rate: 56.380%

## Parlays

- Candidates: 20
- Wins: 7
- Losses: 13
- Pushes: 0
- Profit: 5.512 units
- ROI: 27.562%
- Average expected value: 2.645 units

## Baselines

- Current policy singles ROI: 7.635%
- No-threshold singles ROI: 7.492%
- Top-edge-only singles ROI: 21.488%
- Singles plus top parlay per week ROI: 7.648%

## Diagnostics

- Best stat: `receiving_tds` (ROI=51.370%, profit=1069.000)
- Worst stat: `carries` (ROI=-19.383%, profit=-541.182)
- Best book: `synthetic` (ROI=7.635%, profit=1435.364)
- Worst book: `synthetic` (ROI=7.635%, profit=1435.364)

## Weekly Breakdown

| season | week | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025 | 1 | 977.000 | 558.000 | 419.000 | 0.000 | 977.000 | 88.273 | 9.04% | 57.11% |
| 2025 | 2 | 953.000 | 530.000 | 423.000 | 0.000 | 953.000 | 58.818 | 6.17% | 55.61% |
| 2025 | 3 | 950.000 | 556.000 | 394.000 | 0.000 | 950.000 | 111.455 | 11.73% | 58.53% |
| 2025 | 4 | 1067.000 | 585.000 | 482.000 | 0.000 | 1067.000 | 49.818 | 4.67% | 54.83% |
| 2025 | 5 | 943.000 | 513.000 | 430.000 | 0.000 | 943.000 | 36.364 | 3.86% | 54.40% |
| 2025 | 6 | 970.000 | 558.000 | 412.000 | 0.000 | 970.000 | 95.273 | 9.82% | 57.53% |
| 2025 | 7 | 1035.000 | 541.000 | 494.000 | 0.000 | 1035.000 | -2.182 | -0.21% | 52.27% |
| 2025 | 8 | 883.000 | 479.000 | 404.000 | 0.000 | 883.000 | 31.455 | 3.56% | 54.25% |
| 2025 | 9 | 928.000 | 520.000 | 408.000 | 0.000 | 928.000 | 64.727 | 6.97% | 56.03% |
| 2025 | 10 | 942.000 | 496.000 | 446.000 | 0.000 | 942.000 | 4.909 | 0.52% | 52.65% |
| 2025 | 11 | 1005.000 | 585.000 | 420.000 | 0.000 | 1005.000 | 111.818 | 11.13% | 58.21% |
| 2025 | 12 | 914.000 | 536.000 | 378.000 | 0.000 | 914.000 | 109.273 | 11.96% | 58.64% |

## Stat Breakdown

| stat | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| receiving_tds | 2081.000 | 1650.000 | 431.000 | 0.000 | 2081.000 | 1069.000 | 51.37% | 79.29% |
| rushing_tds | 1026.000 | 789.000 | 237.000 | 0.000 | 1026.000 | 480.273 | 46.81% | 76.90% |
| receptions | 4270.000 | 2367.000 | 1903.000 | 0.000 | 4270.000 | 248.818 | 5.83% | 55.43% |
| receiving_yards | 4111.000 | 2272.000 | 1839.000 | 0.000 | 4111.000 | 226.455 | 5.51% | 55.27% |
| interceptions | 401.000 | 280.000 | 121.000 | 0.000 | 401.000 | 133.545 | 33.30% | 69.83% |
| passing_tds | 587.000 | 366.000 | 221.000 | 0.000 | 587.000 | 111.727 | 19.03% | 62.35% |
| completions | 532.000 | 307.000 | 225.000 | 0.000 | 532.000 | 54.091 | 10.17% | 57.71% |
| passing_yards | 553.000 | 312.000 | 241.000 | 0.000 | 553.000 | 42.636 | 7.71% | 56.42% |
| rushing_yards | 2448.000 | 1078.000 | 1370.000 | 0.000 | 2448.000 | -390.000 | -15.93% | 44.04% |
| carries | 2792.000 | 1179.000 | 1613.000 | 0.000 | 2792.000 | -541.182 | -19.38% | 42.23% |

## Book Breakdown

| book | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic | 18801.000 | 10600.000 | 8201.000 | 0.000 | 18801.000 | 1435.364 | 7.63% | 56.38% |

## Interpretation

Result looks usable enough to keep moving, with positive replay economics after vig on this slice. It still deserves stress checks across seasons, books, and edge buckets before relying on it.

## Top Parlays

- 2025 Week 2: `00-0032764 rushing_yards under | 00-0034844 rushing_yards under` (EV=2.645, joint_prob=1.000, result=win)
- 2025 Week 2: `00-0032764 rushing_yards under | 00-0036223 rushing_yards under` (EV=2.645, joint_prob=1.000, result=loss)
- 2025 Week 2: `00-0032764 rushing_yards under | 00-0036358 receiving_yards under` (EV=2.645, joint_prob=1.000, result=loss)
- 2025 Week 2: `00-0032764 rushing_yards under | 00-0037238 receiving_yards under` (EV=2.645, joint_prob=1.000, result=win)
- 2025 Week 2: `00-0032764 rushing_yards under | 00-0039075 receiving_yards under` (EV=2.645, joint_prob=1.000, result=win)
