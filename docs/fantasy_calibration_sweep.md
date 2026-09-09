# Fantasy downstream calibration — research + sweep log

Spec: `docs/superpowers/specs/2026-09-09-fantasy-downstream-calibration-design.md`
Plan: `docs/superpowers/plans/2026-09-09-fantasy-downstream-calibration.md`

## Research (sets search *bounds*; the 2025 backtest decides the values)

**1. Weekly fantasy-points coefficient of variation by position.**
Public week-to-week variance studies put the CV of weekly PPR points at roughly
**QB ≈ 0.39, RB ≈ 0.63, WR ≈ 0.67, TE ≈ 0.70**. Our per-stat CVs (`yard_cv`
default 0.55, `count_cv` 0.85) feed a moment-matched sum, so the *total-FP* CV
lands a bit under the per-yardage CV for a WR. Implication: the `*_cv` upper
search bound should reach ~1.0–1.2 so the summed total-FP CV can hit the
empirical 0.63–0.70. The driver already allows `yard_cv ∈ [0.45, 1.20]`,
`count_cv ∈ [0.55, 1.30]`.
Sources: playerprofiler.com "Player Variance Manifesto", underdognetwork.com
"Weekly Variance By Position".

**2. Recent form vs regression to the mean.**
Public methodologies regress the *efficiency/rate* stats (TD per target, catch
rate, yards per attempt) toward positional means by sample size, and keep
*volume* closer to observed. Early in the season career baselines dominate; by
~Week 12 recent data outweighs them. Our anchor already does the `n/(n+4)`
shrinkage; the downstream lever here is `glm_blend_weight` (how much the
regression model — which itself regresses rates hard — moves the blended mean)
and the per-stat `glm_bias` on the `*_tds` stats.
Sources: footballguys.com "Regression to the Mean", fantasyprojectionlab.com
"NFL Fantasy Projections", fantasyfootballanalytics.net projection study.

**3. Vegas implied-team-total adjustment magnitude.**
Consensus systems apply roughly a **10–15 % player-projection adjustment for a
6-point implied-total delta** (~2 % per point), varying by position; the spread
matters more for RB / pass-catching TE (game script) than QB. Our
`game_environment` factor at default strength gives ~+6.6 % for a 6-pt delta
(¼-strength) — conservative vs consensus. `factor_strength["game_environment"]`
can rise to 1.5 (→ ~+10 % for a 6-pt delta), so the search space spans the
published range; the backtest picks the point.
Sources: fantasyprojectionlab.com "Vegas Lines and Fantasy Projections",
sharpfootballanalysis.com implied-totals tool, thegamesnap.com implied-totals
playbook.

**4. Boom/bust is a distribution-shape problem, not just a mean problem.**
An inflated boom% for an elite pass-catcher comes from (a) a mean pushed up by
the GLM blend + a collinear "good offense" factor stack and (b) a distribution
that is too tight (the GLM's *fit* std ≪ game-to-game variance). The sweep
addresses both: `glm_bias` + `glm_blend_weight` + `offense_stack_cap` for the
mean, `cv_floor_frac` + `yard_cv`/`count_cv` + `glm_var_inflation` for the
spread. The objective scores boom AND bust calibration per position.

---

## Sweep run
_(appended by scripts/tune_fantasy_calibration.py --run)_
