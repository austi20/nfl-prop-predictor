# Model Revision Comparison

Report: `holdout`
Previous label: `previous_saved`
Current label: `current_run`

Negative delta values for MAE/RMSE mean the current revision improved.

## QB

- `passing_yards`: MAE 80.371 -> 80.261 (delta -0.110), RMSE 101.697 -> 101.576 (delta -0.122), |bias| delta +3.342
- `passing_tds`: MAE 0.969 -> 0.976 (delta +0.007), RMSE 1.158 -> 1.157 (delta -0.001), |bias| delta +0.030
- `interceptions`: MAE 0.681 -> 0.681 (delta +0.000), RMSE 0.804 -> 0.804 (delta +0.000), |bias| delta +0.004
- `completions`: MAE 6.618 -> 6.608 (delta -0.010), RMSE 8.611 -> 8.616 (delta +0.005), |bias| delta +0.302

## RB

- `rushing_yards`: MAE 24.785 -> 24.554 (delta -0.231), RMSE 32.277 -> 32.079 (delta -0.198), |bias| delta +0.003
- `carries`: MAE 4.930 -> 4.847 (delta -0.082), RMSE 5.898 -> 5.805 (delta -0.093), |bias| delta +0.010
- `rushing_tds`: MAE 0.373 -> 0.374 (delta +0.000), RMSE 0.523 -> 0.523 (delta -0.000), |bias| delta +0.001

## WR_TE

- `receptions`: MAE 1.660 -> 1.657 (delta -0.003), RMSE 2.078 -> 2.066 (delta -0.011), |bias| delta +0.053
- `receiving_yards`: MAE 22.597 -> 22.553 (delta -0.043), RMSE 28.939 -> 28.731 (delta -0.208), |bias| delta +0.241
- `receiving_tds`: MAE 0.312 -> 0.314 (delta +0.002), RMSE 0.434 -> 0.434 (delta -0.000), |bias| delta +0.003
