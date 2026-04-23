# Paper Trade Replay 2024-2025

Replay years: 2024, 2025
Minimum edge: 0.050
Stake per bet: 1.00 units

## Validation

- Input rows: 41508
- Rows after filters: 41508
- Rows priced: 41508
- Selected rows: 36360
- Skipped unsupported stat: 0
- Skipped missing odds: 0
- Skipped missing actual outcome: 0
- No selection because edge threshold not met: 5148

## Singles

- Bets: 36360
- Wins: 20173
- Losses: 16187
- Pushes: 0
- Profit: 2152.091 units
- ROI: 5.919%
- Win rate: 55.481%

## Parlays

- Candidates: 20
- Wins: 12
- Losses: 8
- Pushes: 0
- Profit: 23.736 units
- ROI: 118.678%
- Average expected value: 2.645 units

## Baselines

- Current policy singles ROI: 5.919%
- No-threshold singles ROI: 5.484%
- Top-edge-only singles ROI: 21.488%
- Singles plus top parlay per week ROI: 5.941%

## Diagnostics

- Best stat: `receiving_tds` (ROI=52.086%, profit=2138.636)
- Worst stat: `carries` (ROI=-20.883%, profit=-1155.455)
- Best book: `synthetic` (ROI=5.919%, profit=2152.091)
- Worst book: `synthetic` (ROI=5.919%, profit=2152.091)

## Weekly Breakdown

| season | week | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 1 | 901.000 | 506.000 | 395.000 | 0.000 | 901.000 | 65.000 | 7.21% | 56.16% |
| 2024 | 2 | 921.000 | 516.000 | 405.000 | 0.000 | 921.000 | 64.091 | 6.96% | 56.03% |
| 2024 | 3 | 916.000 | 487.000 | 429.000 | 0.000 | 916.000 | 13.727 | 1.50% | 53.17% |
| 2024 | 4 | 954.000 | 532.000 | 422.000 | 0.000 | 954.000 | 61.636 | 6.46% | 55.77% |
| 2024 | 5 | 858.000 | 478.000 | 380.000 | 0.000 | 858.000 | 54.545 | 6.36% | 55.71% |
| 2024 | 6 | 856.000 | 494.000 | 362.000 | 0.000 | 856.000 | 87.091 | 10.17% | 57.71% |
| 2024 | 7 | 973.000 | 544.000 | 429.000 | 0.000 | 973.000 | 65.545 | 6.74% | 55.91% |
| 2024 | 8 | 1028.000 | 563.000 | 465.000 | 0.000 | 1028.000 | 46.818 | 4.55% | 54.77% |
| 2024 | 9 | 952.000 | 531.000 | 421.000 | 0.000 | 952.000 | 61.727 | 6.48% | 55.78% |
| 2024 | 10 | 892.000 | 512.000 | 380.000 | 0.000 | 892.000 | 85.455 | 9.58% | 57.40% |
| 2024 | 11 | 939.000 | 523.000 | 416.000 | 0.000 | 939.000 | 59.455 | 6.33% | 55.70% |
| 2024 | 12 | 877.000 | 457.000 | 420.000 | 0.000 | 877.000 | -4.545 | -0.52% | 52.11% |

## Stat Breakdown

| stat | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| receiving_tds | 4106.000 | 3271.000 | 835.000 | 0.000 | 4106.000 | 2138.636 | 52.09% | 79.66% |
| rushing_tds | 2014.000 | 1547.000 | 467.000 | 0.000 | 2014.000 | 939.364 | 46.64% | 76.81% |
| interceptions | 1030.000 | 676.000 | 354.000 | 0.000 | 1030.000 | 260.545 | 25.30% | 65.63% |
| passing_tds | 1203.000 | 746.000 | 457.000 | 0.000 | 1203.000 | 221.182 | 18.39% | 62.01% |
| receiving_yards | 7765.000 | 4182.000 | 3583.000 | 0.000 | 7765.000 | 218.818 | 2.82% | 53.86% |
| completions | 958.000 | 572.000 | 386.000 | 0.000 | 958.000 | 134.000 | 13.99% | 59.71% |
| passing_yards | 966.000 | 570.000 | 396.000 | 0.000 | 966.000 | 122.182 | 12.65% | 59.01% |
| receptions | 8078.000 | 4264.000 | 3814.000 | 0.000 | 8078.000 | 62.364 | 0.77% | 52.79% |
| rushing_yards | 4707.000 | 2052.000 | 2655.000 | 0.000 | 4707.000 | -789.545 | -16.77% | 43.59% |
| carries | 5533.000 | 2293.000 | 3240.000 | 0.000 | 5533.000 | -1155.455 | -20.88% | 41.44% |

## Book Breakdown

| book | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| synthetic | 36360.000 | 20173.000 | 16187.000 | 0.000 | 36360.000 | 2152.091 | 5.92% | 55.48% |

## Interpretation

Result looks usable enough to keep moving, with positive replay economics after vig on this slice. It still deserves stress checks across seasons, books, and edge buckets before relying on it.

## Top Parlays

- 2024 Week 17: `00-0026300 passing_yards over | 00-0036928 passing_yards over` (EV=2.645, joint_prob=1.000, result=loss)
- 2024 Week 17: `00-0026300 passing_yards over | 00-0033869 passing_yards over` (EV=2.645, joint_prob=1.000, result=win)
- 2024 Week 17: `00-0036928 passing_yards over | 00-0033869 passing_yards over` (EV=2.645, joint_prob=1.000, result=loss)
- 2024 Week 18: `00-0034401 passing_yards over | 00-0038582 passing_yards over` (EV=2.645, joint_prob=1.000, result=loss)
- 2025 Week 2: `00-0038416 passing_yards over | 00-0036223 carries under` (EV=2.645, joint_prob=1.000, result=win)
