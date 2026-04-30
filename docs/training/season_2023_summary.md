# Training Season 2022

**Holdout:** 2023

## Headline metrics (best config)
- Best k: 2
- L1 alpha: 0.001
- Distribution family: count_aware
- Feature set: base_only
- Log-loss: 0.8668 (Δ vs naive: +0.1737)
- Brier: 0.2622
- Reliability max deviation: 0.4419

## Top 3 features by coefficient magnitude
  pos    stat                 log_loss
  wr_te  receiving_tds        0.4712
  rb     rushing_tds          0.5336
  qb     interceptions        0.5797

## Ablation findings
- Weather on vs off: -0.0000 (on=0.8999, off=0.8999)
- Opponent EPA on vs off: N/A (H2.1 deferred)
- Rest days on vs off: N/A (H2.1 deferred)
- Distribution family delta (legacy → count_aware → decomposed):   legacy: 0.9281
  count_aware: 0.8858
  decomposed: 0.8858

## Qualitative observations
The model's performance shows a slight improvement in log-loss (0.8668 vs naive +0.1737) and lower Brier score (0.2622), indicating better predictive accuracy. The top features—receiving_tds, rushing_tds, and interceptions—suggest the model prioritizes statistical outcomes over other factors. The distribution family transition from legacy to count_aware slightly reduced performance, highlighting the importance of appropriate modeling choices.
