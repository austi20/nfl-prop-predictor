# Paper Trade Replay 2024

Replay years: 2024
Minimum edge: 0.050
Stake per bet: 1.00 units

## Validation

- Input rows: 8
- Rows after filters: 8
- Rows priced: 8
- Selected rows: 8
- Skipped unsupported stat: 0
- Skipped missing odds: 0
- Skipped missing actual outcome: 0
- No selection because edge threshold not met: 0

## Singles

- Bets: 8
- Wins: 7
- Losses: 1
- Pushes: 0
- Profit: 3.625 units
- ROI: 45.309%
- Win rate: 87.500%

## Parlays

- Candidates: 10
- Wins: 5
- Losses: 5
- Pushes: 0
- Profit: 4.656 units
- ROI: 46.555%
- Average expected value: 1.668 units

## Baselines

- Current policy singles ROI: 45.309%
- No-threshold singles ROI: 45.309%
- Top-edge-only singles ROI: -100.000%
- Singles plus top parlay per week ROI: 29.164%

## Diagnostics

- Best stat: `passing_yards` (ROI=90.909%, profit=0.909)
- Worst stat: `receptions` (ROI=-100.000%, profit=-1.000)
- Best book: `demo_book` (ROI=45.309%, profit=3.625)
- Worst book: `demo_book` (ROI=45.309%, profit=3.625)

## Weekly Breakdown

| season | week | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 10 | 8.000 | 7.000 | 1.000 | 0.000 | 8.000 | 3.625 | 45.31% | 87.50% |

## Stat Breakdown

| stat | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| receiving_yards | 2.000 | 2.000 | 0.000 | 0.000 | 2.000 | 1.347 | 67.34% | 100.00% |
| rushing_yards | 2.000 | 2.000 | 0.000 | 0.000 | 2.000 | 1.147 | 57.33% | 100.00% |
| passing_yards | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 0.909 | 90.91% | 100.00% |
| carries | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 0.667 | 66.67% | 100.00% |
| passing_tds | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 0.556 | 55.56% | 100.00% |
| receptions | 1.000 | 0.000 | 1.000 | 0.000 | 1.000 | -1.000 | -100.00% | 0.00% |

## Book Breakdown

| book | n_bets | wins | losses | pushes | staked_units | profit_units | roi | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| demo_book | 8.000 | 7.000 | 1.000 | 0.000 | 8.000 | 3.625 | 45.31% | 87.50% |

## Interpretation

Result looks noisy because the replay sample is still small. Treat it as a pipeline verification run more than a strategy verdict.

## Top Parlays

- 2024 Week 10: `00-0039075 receptions under | 00-0036223 carries under` (EV=2.299, joint_prob=0.860, result=loss)
- 2024 Week 10: `00-0039075 receptions under | 00-0033873 passing_yards under` (EV=1.943, joint_prob=0.670, result=loss)
- 2024 Week 10: `00-0039075 receptions under | 00-0038542 rushing_yards under` (EV=1.898, joint_prob=0.818, result=loss)
- 2024 Week 10: `00-0039075 receptions under | 00-0036223 rushing_yards under` (EV=1.795, joint_prob=0.757, result=loss)
- 2024 Week 10: `00-0039075 receptions under | 00-0037238 receiving_yards under` (EV=1.712, joint_prob=0.734, result=loss)
