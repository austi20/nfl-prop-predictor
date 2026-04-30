# Training Season 2021

**Holdout:** 2022

## Headline metrics (best config)
- Best k: 2
- L1 alpha: 0.0
- Distribution family: count_aware
- Feature set: weather
- Log-loss: 0.8784 (Δ vs naive: +0.1853)
- Brier: 0.2629
- Reliability max deviation: 0.3569

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.4445
  rb     rushing_tds          0.5080
  qb     interceptions        0.6157

## Ablation findings
- Weather on vs off: -0.0000 (on=0.9076, off=0.9076)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 0.9324
  count_aware: 0.8992
  decomposed: 0.8911

## Qualitative observations
The model shows strong performance in predicting receiving touchdowns for wide receivers, with a log-loss of 0.4445, while rushing touchdowns for running backs and interceptions for quarterbacks are more uncertain, as indicated by higher log-loss values. The count_aware distribution family yields slightly lower log-loss compared to the legacy approach, suggesting improved model stability.
