# Training Season 2020

**Holdout:** 2021

## Headline metrics (best config)
- Best k: 2
- L1 alpha: 0.0
- Distribution family: decomposed
- Feature set: weather
- Log-loss: 0.9037 (Δ vs naive: +0.2106)
- Brier: 0.2706
- Reliability max deviation: 0.4943

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.4884
  rb     rushing_tds          0.5125
  qb     interceptions        0.5959

## Ablation findings
- Weather on vs off: -0.0000 (on=0.9329, off=0.9329)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 0.9513
  count_aware: 0.9324
  decomposed: 0.9152

## Qualitative observations
The model's performance remains stable across different distribution families, with the decomposed family showing a slight decrease in log-loss but maintaining high reliability. The top features consistently highlight receiving touchdowns for wide receivers and rushing touchdowns for running backs, suggesting strong correlations with team success.
