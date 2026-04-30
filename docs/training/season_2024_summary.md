# Training Season 2023

**Holdout:** 2024

## Headline metrics (best config)
- Best k: 2
- L1 alpha: 0.0
- Distribution family: decomposed
- Feature set: weather
- Log-loss: 0.8759 (Δ vs naive: +0.1828)
- Brier: 0.2661
- Reliability max deviation: 0.4501

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.4771
  rb     rushing_tds          0.5204
  qb     interceptions        0.5978

## Ablation findings
- Weather on vs off: -0.0000 (on=0.9070, off=0.9070)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 0.9367
  count_aware: 0.8976
  decomposed: 0.8867

## Qualitative observations
The model's performance remains stable across different distribution families, with a slight decrease in log-loss from legacy to count_aware to decomposed. The top features consistently highlight receiving touchdowns for wide receivers and rushing touchdowns for running backs, suggesting these stats are strongly associated with the model's predictions.
