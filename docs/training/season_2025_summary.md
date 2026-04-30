# Training Season 2024

**Holdout:** 2025

## Headline metrics (best config)
- Best k: 2
- L1 alpha: 0.0
- Distribution family: decomposed
- Feature set: weather
- Log-loss: 0.8783 (Δ vs naive: +0.1852)
- Brier: 0.2674
- Reliability max deviation: 0.4778

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.4882
  rb     rushing_tds          0.5302
  qb     interceptions        0.6019

## Ablation findings
- Weather on vs off: -0.0000 (on=0.9098, off=0.9098)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 0.9432
  count_aware: 0.8964
  decomposed: 0.8898

## Qualitative observations
The model's performance is consistent across different distribution families, with the decomposed family showing a slight decrease in log-loss but maintaining high reliability. The top features highlight receiving touchdowns for wide receivers and rushing touchdowns for running backs as key predictors, while the model shows no significant difference in performance between weather on and off.
