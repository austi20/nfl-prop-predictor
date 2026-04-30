# Training Season 2019

**Holdout:** 2020

## Headline metrics (best config)
- Best k: 6
- L1 alpha: 0.001
- Distribution family: decomposed
- Feature set: base_only
- Log-loss: 0.9224 (Δ vs naive: +0.2293)
- Brier: 0.2756
- Reliability max deviation: 0.4984

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.5086
  rb     rushing_tds          0.5224
  qb     interceptions        0.6047

## Ablation findings
- Weather on vs off: +0.0095 (on=1.0086, off=0.9992)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 1.0414
  count_aware: 1.0053
  decomposed: 0.9649

## Qualitative observations
The model's performance is most strongly influenced by receiving_tds for wide receivers, followed by rushing_tds for running backs, and interceptions for quarterbacks. The log-loss values indicate that the model places higher importance on these stats compared to others, suggesting a focus on key offensive contributions.
