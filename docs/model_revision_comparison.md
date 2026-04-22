# Model Revision Comparison

Report: `walk_forward`
Previous label: `previous_saved`
Current label: `current_run`

Negative delta values for MAE/RMSE mean the current revision improved.

## QB

- `passing_yards`: MAE 79.086 -> 78.839 (delta -0.247), RMSE 100.817 -> 100.383 (delta -0.434), |bias| delta +1.526
- `passing_tds`: MAE 0.954 -> 0.956 (delta +0.002), RMSE 1.142 -> 1.141 (delta -0.001), |bias| delta +0.009
- `interceptions`: MAE 0.719 -> 0.719 (delta -0.001), RMSE 0.867 -> 0.867 (delta -0.000), |bias| delta +0.002
- `completions`: MAE 6.641 -> 6.616 (delta -0.024), RMSE 8.560 -> 8.515 (delta -0.046), |bias| delta +0.168

## RB

- `rushing_yards`: MAE 25.687 -> 25.553 (delta -0.133), RMSE 33.098 -> 32.923 (delta -0.175), |bias| delta +0.150
- `carries`: MAE 5.019 -> 4.967 (delta -0.052), RMSE 6.107 -> 6.045 (delta -0.062), |bias| delta +0.029
- `rushing_tds`: MAE 0.400 -> 0.400 (delta -0.000), RMSE 0.543 -> 0.542 (delta -0.001), |bias| delta -0.001

## WR_TE

- `receptions`: MAE 1.746 -> 1.742 (delta -0.005), RMSE 2.205 -> 2.196 (delta -0.009), |bias| delta +0.022
- `receiving_yards`: MAE 24.846 -> 24.762 (delta -0.084), RMSE 31.832 -> 31.676 (delta -0.156), |bias| delta +0.280
- `receiving_tds`: MAE 0.361 -> 0.361 (delta +0.000), RMSE 0.475 -> 0.475 (delta -0.000), |bias| delta +0.001
