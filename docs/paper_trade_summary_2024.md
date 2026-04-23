# Paper Trade Replay 2024

Replay years: 2024
Minimum edge: 0.050
Stake per bet: 1.00 units

## Validation

- Input rows: 41508
- Rows after filters: 20561
- Rows priced: 19433
- Selected rows: 16935
- Skipped unsupported stat: 0
- Skipped missing odds: 0
- Skipped missing actual outcome: 1128
- No selection because edge threshold not met: 2498

## Singles

- Bets: 16935
- Wins: 9739
- Losses: 7196
- Pushes: 0
- Profit: 1657.636 units
- ROI: 9.788%
- Win rate: 57.508%

## Parlays

- Candidates: 20
- Wins: 7
- Losses: 13
- Pushes: 0
- Profit: 5.512 units
- ROI: 27.562%
- Average expected value: 2.645 units

## Baselines

- Current policy singles ROI: 9.788%
- No-threshold singles ROI: 8.156%
- Top-edge-only singles ROI: -4.545%
- Singles plus top parlay per week ROI: 9.790%

## Diagnostics

- Best stat: `receiving_tds` (ROI=51.270%, profit=1007.455)
- Worst stat: `carries` (ROI=-16.532%, profit=-431.818)
- Best book: `synthetic` (ROI=9.788%, profit=1657.636)
- Worst book: `synthetic` (ROI=9.788%, profit=1657.636)

## Weekly Breakdown

| season | week | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 1 | 861.000 | 490.000 | 371.000 | 0.000 | 861.000 | 74.455 | 8.65% | 56.91% |
| 2024 | 2 | 856.000 | 508.000 | 348.000 | 0.000 | 856.000 | 113.818 | 13.30% | 59.35% |
| 2024 | 3 | 877.000 | 481.000 | 396.000 | 0.000 | 877.000 | 41.273 | 4.71% | 54.85% |
| 2024 | 4 | 894.000 | 520.000 | 374.000 | 0.000 | 894.000 | 98.727 | 11.04% | 58.17% |
| 2024 | 5 | 816.000 | 472.000 | 344.000 | 0.000 | 816.000 | 85.091 | 10.43% | 57.84% |
| 2024 | 6 | 831.000 | 492.000 | 339.000 | 0.000 | 831.000 | 108.273 | 13.03% | 59.21% |
| 2024 | 7 | 916.000 | 530.000 | 386.000 | 0.000 | 916.000 | 95.818 | 10.46% | 57.86% |
| 2024 | 8 | 972.000 | 540.000 | 432.000 | 0.000 | 972.000 | 58.909 | 6.06% | 55.56% |
| 2024 | 9 | 899.000 | 514.000 | 385.000 | 0.000 | 899.000 | 82.273 | 9.15% | 57.17% |
| 2024 | 10 | 822.000 | 483.000 | 339.000 | 0.000 | 822.000 | 100.091 | 12.18% | 58.76% |
| 2024 | 11 | 866.000 | 500.000 | 366.000 | 0.000 | 866.000 | 88.545 | 10.22% | 57.74% |
| 2024 | 12 | 806.000 | 438.000 | 368.000 | 0.000 | 806.000 | 30.182 | 3.74% | 54.34% |

## Stat Breakdown

| stat | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| receiving_tds | 1965.000 | 1557.000 | 408.000 | 0.000 | 1965.000 | 1007.455 | 51.27% | 79.24% |
| rushing_tds | 971.000 | 744.000 | 227.000 | 0.000 | 971.000 | 449.364 | 46.28% | 76.62% |
| receptions | 3479.000 | 2007.000 | 1472.000 | 0.000 | 3479.000 | 352.545 | 10.13% | 57.69% |
| receiving_yards | 3627.000 | 2000.000 | 1627.000 | 0.000 | 3627.000 | 191.182 | 5.27% | 55.14% |
| interceptions | 509.000 | 335.000 | 174.000 | 0.000 | 509.000 | 130.545 | 25.65% | 65.82% |
| passing_tds | 592.000 | 369.000 | 223.000 | 0.000 | 592.000 | 112.455 | 19.00% | 62.33% |
| passing_yards | 494.000 | 293.000 | 201.000 | 0.000 | 494.000 | 65.364 | 13.23% | 59.31% |
| completions | 475.000 | 283.000 | 192.000 | 0.000 | 475.000 | 65.273 | 13.74% | 59.58% |
| rushing_yards | 2211.000 | 1009.000 | 1202.000 | 0.000 | 2211.000 | -284.727 | -12.88% | 45.64% |
| carries | 2612.000 | 1142.000 | 1470.000 | 0.000 | 2612.000 | -431.818 | -16.53% | 43.72% |

## Book Breakdown

| book | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic | 16935.000 | 9739.000 | 7196.000 | 0.000 | 16935.000 | 1657.636 | 9.79% | 57.51% |

## Interpretation

Result looks usable enough to keep moving, with positive replay economics after vig on this slice. It still deserves stress checks across seasons, books, and edge buckets before relying on it.

## Top Parlays

- 2024 Week 17: `00-0026300 passing_yards over | 00-0036928 passing_yards over` (EV=2.645, joint_prob=1.000, result=loss)
- 2024 Week 17: `00-0026300 passing_yards over | 00-0033869 passing_yards over` (EV=2.645, joint_prob=1.000, result=win)
- 2024 Week 17: `00-0036928 passing_yards over | 00-0033869 passing_yards over` (EV=2.645, joint_prob=1.000, result=loss)
- 2024 Week 18: `00-0034401 passing_yards over | 00-0038582 passing_yards over` (EV=2.645, joint_prob=1.000, result=loss)
- 2024 Week 18: `00-0038582 passing_yards over | 00-0034401 completions over` (EV=2.645, joint_prob=1.000, result=loss)
