# Preseason Baseline (uncalibrated)

Uncalibrated GLM performance per (position, stat) on the most recent training year (2025). Frozen reference for the preseason activation gate — see docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md §3.

| position | stat | n | brier | log_loss |
|---|---|---:|---:|---:|
| qb | completions | 649 | 0.2622 | 0.7673 |
| qb | interceptions | 567 | 0.2085 | 0.6019 |
| qb | passing_tds | 617 | 0.2299 | 0.6523 |
| qb | passing_yards | 649 | 0.2612 | 0.7585 |
| rb | carries | 2925 | 0.4558 | 2.3481 |
| rb | rushing_tds | 1029 | 0.1735 | 0.5303 |
| rb | rushing_yards | 2749 | 0.3671 | 1.0712 |
| wr_te | receiving_tds | 2084 | 0.1572 | 0.4889 |
| wr_te | receiving_yards | 4898 | 0.2748 | 0.7760 |
| wr_te | receptions | 4941 | 0.2807 | 0.7972 |

