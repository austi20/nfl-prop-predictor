# Training Season 2018

**Holdout:** 2019

## Headline metrics (best config)
- Best k: 2
- L1 alpha: 0.0
- Distribution family: decomposed
- Feature set: base_only
- Log-loss: 0.9640 (Δ vs naive: +0.2709)
- Brier: 0.2788
- Reliability max deviation: 0.4825

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.4979
  rb     rushing_tds          0.5406
  qb     interceptions        0.6085

## Ablation findings
- Weather on vs off: +0.0000 (on=1.0702, off=1.0702)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 1.0204
  count_aware: 1.1158
  decomposed: 1.0957

## Qualitative observations
The model's performance is consistent across different configurations, with log-loss values indicating moderate predictive accuracy. The top features highlight receiving touchdowns for wide receivers and rushing touchdowns for running backs as key predictors, while interceptions for quarterbacks show higher importance. The reliability max deviation suggests variability in predictions, which may be influenced by the distribution family used.
