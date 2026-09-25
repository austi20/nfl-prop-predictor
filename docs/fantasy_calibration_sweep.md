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

Analytic P(boom) vs real 5000-sim `project_fantasy_points` MC on a 200-row
2025 subsample: mean |diff| = **0.010** (acceptance bar 0.05). The fast
evaluator's boom/bust probabilities track the real Monte Carlo.

## Sweep run
GLM correction (bias): {"QB/interceptions": 0.6, "QB/passing_tds": 0.7646582742085342, "QB/passing_yards": 0.9756218366009062, "RB/rushing_tds": 0.6, "RB/rushing_yards": 0.8507475129809026, "TE/receiving_tds": 0.6, "TE/receiving_yards": 0.6, "TE/receptions": 0.8216926869350862, "WR/receiving_tds": 0.6, "WR/receiving_yards": 0.7257711627494392, "WR/receptions": 0.75642965204236}
GLM correction (var_inflation): {"QB/interceptions": 1.11, "QB/passing_tds": 0.93, "QB/passing_yards": 1.06, "RB/rushing_tds": 1.11, "RB/rushing_yards": 1.3, "TE/receiving_tds": 0.93, "TE/receiving_yards": 1.23, "TE/receptions": 1.3, "WR/receiving_tds": 0.93, "WR/receiving_yards": 1.24, "WR/receptions": 1.08}
post-correction baseline: obj=2.959 mae=5.02 |bias|=0.30 boom_err=0.052 bust_err=0.066 rank=0.575 realism=0.00
    QB:mae6.9/bias+0.4/max27/boom0.09v0.14 | RB:mae4.9/bias-0.1/max23/boom0.04v0.08 | WR:mae4.4/bias+0.1/max19/boom0.03v0.07 | TE:mae3.9/bias-0.6/max17/boom0.04v0.11

### Phase 1 — coarse grid
phase-1 best (bw=0.25 yc=1.0 cap=1.06 cvf=0.7): obj=2.835 mae=5.04 |bias|=0.29 boom_err=0.044 bust_err=0.059 rank=0.575 realism=0.00
    QB:mae6.9/bias+0.4/max27/boom0.12v0.14 | RB:mae4.9/bias-0.0/max23/boom0.05v0.08 | WR:mae4.5/bias+0.2/max18/boom0.03v0.07 | TE:mae3.9/bias-0.5/max17/boom0.04v0.11

### Phase 2 — coordinate descent
pass 1: obj=2.771 mae=5.03 |bias|=0.29 boom_err=0.039 bust_err=0.059 rank=0.580 realism=0.00
    QB:mae6.8/bias+0.5/max26/boom0.13v0.14 | RB:mae4.9/bias+0.0/max23/boom0.05v0.08 | WR:mae4.5/bias+0.2/max19/boom0.04v0.07 | TE:mae3.9/bias-0.5/max17/boom0.05v0.11
pass 2: obj=2.732 mae=5.01 |bias|=0.27 boom_err=0.040 bust_err=0.061 rank=0.583 realism=0.00
    QB:mae6.8/bias+0.4/max26/boom0.12v0.14 | RB:mae4.9/bias-0.0/max23/boom0.05v0.08 | WR:mae4.5/bias+0.1/max18/boom0.04v0.07 | TE:mae3.9/bias-0.6/max17/boom0.04v0.11
pass 3: obj=2.676 mae=5.01 |bias|=0.28 boom_err=0.043 bust_err=0.053 rank=0.586 realism=0.00
    QB:mae6.8/bias+0.5/max25/boom0.12v0.14 | RB:mae4.9/bias+0.0/max23/boom0.05v0.08 | WR:mae4.5/bias+0.1/max19/boom0.03v0.07 | TE:mae3.9/bias-0.5/max17/boom0.04v0.11
pass 4: obj=2.651 mae=5.01 |bias|=0.27 boom_err=0.044 bust_err=0.051 rank=0.587 realism=0.00
    QB:mae6.8/bias+0.4/max25/boom0.11v0.14 | RB:mae4.9/bias+0.0/max23/boom0.05v0.08 | WR:mae4.5/bias+0.1/max19/boom0.03v0.07 | TE:mae3.9/bias-0.5/max17/boom0.04v0.11

### Phase 3 — random local polish
phase-3 best: obj=2.577 mae=4.99 |bias|=0.27 boom_err=0.044 bust_err=0.050 rank=0.595 realism=0.00
    QB:mae6.8/bias+0.5/max24/boom0.11v0.14 | RB:mae4.9/bias+0.0/max23/boom0.05v0.08 | WR:mae4.4/bias-0.0/max19/boom0.03v0.07 | TE:mae3.9/bias-0.6/max16/boom0.04v0.11

## FINAL
```json
{
  "context_clamp_hi": 1.1369348849505485,
  "context_clamp_lo": 0.8803098778643416,
  "count_cv": 1.3,
  "cv_floor_frac": 0.6689391447924465,
  "factor_strength": {
    "coaching": 0.995942621175949,
    "game_environment": 1.0529945537570704,
    "game_script": 0.7803145589984436,
    "news": 1.40890852958264,
    "opponent_matchup": 1.1713154978369489,
    "position_group_form": 0.8237151579568591,
    "qb_support": 1.4149949837302007,
    "rest": 0.01589792855126458,
    "usage_trend": 0.13400872366025476,
    "weather": 0.6872475570230145
  },
  "glm_bias": {
    "QB/interceptions": 0.6,
    "QB/passing_tds": 0.7646582742085342,
    "QB/passing_yards": 0.9756218366009062,
    "RB/rushing_tds": 0.6,
    "RB/rushing_yards": 0.8507475129809026,
    "TE/receiving_tds": 0.6,
    "TE/receiving_yards": 0.6,
    "TE/receptions": 0.8216926869350862,
    "WR/receiving_tds": 0.6,
    "WR/receiving_yards": 0.7257711627494392,
    "WR/receptions": 0.75642965204236
  },
  "glm_blend_weight": 0.27454531604001053,
  "glm_var_inflation": {
    "QB/interceptions": 1.11,
    "QB/passing_tds": 0.93,
    "QB/passing_yards": 1.06,
    "RB/rushing_tds": 1.11,
    "RB/rushing_yards": 1.3,
    "TE/receiving_tds": 0.93,
    "TE/receiving_yards": 1.23,
    "TE/receptions": 1.3,
    "WR/receiving_tds": 0.93,
    "WR/receiving_yards": 1.24,
    "WR/receptions": 1.08
  },
  "offense_stack_cap": 1.03,
  "stat_mean_hi": 1.6881945583267484,
  "stat_mean_lo": 0.45,
  "yard_cv": 0.9465839793162922
}
```
final metrics:
```json
{
  "objective": 2.5766680656120187,
  "mae": 4.986673910901703,
  "bias_abs": 0.27156057960890867,
  "boom_calib_err": 0.04392406154065111,
  "bust_calib_err": 0.049814295808183806,
  "realism_penalty": 0.0,
  "rank_corr": 0.5945422622489543,
  "n": 2741,
  "per_position": {
    "QB": {
      "n": 641,
      "mae": 6.758137944345711,
      "bias": 0.46571796911523144,
      "boom_calib_err": 0.029091826111856997,
      "bust_calib_err": 0.08742071657492427,
      "realism_penalty": 0.0,
      "rank_corr": 0.44365787302571463,
      "max_proj": 24.088316094902694,
      "pred_boom_rate": 0.11124535268524546,
      "actual_boom_rate": 0.1372854914196568
    },
    "RB": {
      "n": 700,
      "mae": 4.892840555724242,
      "bias": 0.03135076954379684,
      "boom_calib_err": 0.03663807468936873,
      "bust_calib_err": 0.03150299509886847,
      "realism_penalty": 0.0,
      "rank_corr": 0.6901068480518563,
      "max_proj": 22.82087557682213,
      "pred_boom_rate": 0.04764763959634555,
      "actual_boom_rate": 0.08428571428571428
    },
    "WR": {
      "n": 700,
      "mae": 4.425082558539566,
      "bias": -0.0047118154332143345,
      "boom_calib_err": 0.03954041228413493,
      "bust_calib_err": 0.05210367707940705,
      "realism_penalty": 0.0,
      "rank_corr": 0.6452738959717826,
      "max_proj": 18.70030940444091,
      "pred_boom_rate": 0.030035310240329065,
      "actual_boom_rate": 0.06857142857142857
    },
    "TE": {
      "n": 700,
      "mae": 3.8706345849972936,
      "bias": -0.584461764343392,
      "boom_calib_err": 0.07042593307724376,
      "bust_calib_err": 0.028229794479535435,
      "realism_penalty": 0.0,
      "rank_corr": 0.5991304319464638,
      "max_proj": 16.08437607120666,
      "pred_boom_rate": 0.04082250446440939,
      "actual_boom_rate": 0.10857142857142857
    }
  }
}
```

written -> models\fantasy_calibration.json

---

## Final metrics — 2025 backtest (per-position-balanced), DEFAULT vs TUNED

Fit on 2023-2024 (GLM correction), scored on 2025. `n=2741` (QB 641, RB/WR/TE 700).

| metric (pos-balanced) | DEFAULT | +GLM correction | TUNED |
|---|---|---|---|
| objective | 3.304 | 2.959 | **2.577** |
| MAE | 5.12 | 5.02 | **4.99** |
| \|bias\| | 0.48 | 0.30 | **0.27** |
| boom calib err | 0.047 | 0.052 | **0.044** |
| bust calib err | 0.066 | 0.066 | **0.050** |
| rank corr | 0.574 | 0.575 | **0.595** |
| realism penalty | 0.00 | 0.00 | 0.00 |

Per-position rank correlation (must not drop > 0.03): QB 0.401 -> **0.444**,
RB 0.674 -> **0.690**, WR 0.635 -> **0.645**, TE 0.586 -> **0.599**. All rose.

Per-position MAE / bias, DEFAULT -> TUNED:
QB 6.89/+0.74 -> 6.76/+0.47 · RB 4.98/+0.29 -> 4.89/+0.03 ·
WR 4.60/+0.83 -> 4.43/-0.00 · TE 4.00/+0.08 -> 3.87/**-0.58**.

TE now runs ~0.6 pts low-centered: the GLM correction's TE haircuts
(`receiving_yards` 0.60, `receiving_tds` 0.60, `receptions` 0.82) are aggressive
because the shared wr_te GLM over-projects TE volume. TE MAE and rank still
improved; post-Week-1 real data re-anchors this.

## Final config — deltas from the built-in default

| field | default | tuned | effect |
|---|---|---|---|
| `glm_blend_weight` | 0.35 | 0.275 | less weight on the (elite-tail-inflating) regression model |
| `stat_mean_hi` | 1.70 | 1.688 | ~unchanged |
| `stat_mean_lo` | 0.45 | 0.45 | unchanged |
| `yard_cv` | 0.55 | 0.947 | wider no-GLM yardage spread |
| `count_cv` | 0.85 | 1.30 | wider no-GLM count spread (hit ceiling) |
| `cv_floor_frac` | 0.0 | 0.669 | **new** — per-game std floored at 0.669·cv·mean; deflates the too-tight GLM boom% |
| `context_clamp_hi` | 1.22 | 1.137 | caps total positive context boost |
| `context_clamp_lo` | 0.78 | 0.880 | context can't gut a projection |
| `offense_stack_cap` | 1.30 | 1.03 | **the collinear game_environment × coaching × qb_support trio is capped at 1.03x combined** — stops triple-counting "good offense" |
| `factor_strength.game_environment` | 1.0 | 1.053 | |
| `factor_strength.coaching` | 1.0 | 0.996 | |
| `factor_strength.opponent_matchup` | 1.0 | 1.171 | |
| `factor_strength.usage_trend` | 1.0 | 0.134 | 2025 sample shows ~no predictive signal (data often 404s); factor stays wired + shown |
| `factor_strength.rest` | 1.0 | 0.016 | 2025 sample shows ~no signal (few non-standard-rest rows); factor stays wired + shown |
| `factor_strength.news` | 1.0 | 1.409 | |
| `factor_strength.qb_support` | 1.0 | 1.415 | |
| `factor_strength.position_group_form` | 1.0 | 0.824 | |
| `factor_strength.weather` | 1.0 | 0.687 | |
| `factor_strength.game_script` | 1.0 | 0.780 | |
| `glm_bias` / `glm_var_inflation` | {} | see `models/fantasy_glm_correction.json` | analytic, fit on 2023-2024 |

Every context factor is still computed and still rendered in the projection
breakdown; `factor_strength` only scales each factor's `(multiplier - 1)`
deviation. Nothing was removed.

## 2026 Week-1 board — real 5000-sim `project_fantasy_points` (full PPR)

| pos | top 6 (proj / boom%) |
|---|---|
| RB | Robinson 17.3/.34 · Gibbs 17.3/.32 · Henry 17.2/.37 · Brown 17.1/.33 · McCaffrey 16.3/.28 · Williams 14.9/.23 |
| WR | **Nacua 22.5/.61** · Brown 18.6/.45 · Olave 18.3/.43 · Chase 17.6/.40 · Nabers 15.1/.27 · Flowers 14.9/.24 |
| TE | Loveland 14.8/.54 · McBride 14.4/.53 · Pitts 13.5/.47 · Kittle 11.2/.31 · Bowers 11.0/.30 · Kraft 10.3/.24 |
| QB | Lawrence 20.9/.36 · Stafford 20.2/.34 · Dart 20.0/.30 · Burrow 19.0/.29 · Allen 18.1/.24 · Williams 18.0/.25 |

Nacua: **30.4 / 0.84 boom -> 22.5 / 0.61 boom.** The user's stated realistic band
was "21, even 25". Boom 0.61 is marginally above the 0.35-0.60 target for a
clear WR1 in a high-total offense but well under the 0.70 remediation trigger.
QB cluster 18-21 and rookie-QB thin-sample leak (Dart 20.0) are pre-existing and
tracked separately (post-Week-1 real data, not an eve-of-season change).

## Sweep run
GLM correction (bias): {"QB/interceptions": 0.6, "QB/passing_tds": 0.7646582742085342, "QB/passing_yards": 0.9756218366009062, "RB/rushing_tds": 0.6, "RB/rushing_yards": 0.8507475129809026, "TE/receiving_tds": 0.6, "TE/receiving_yards": 0.6, "TE/receptions": 0.8216926869350862, "WR/receiving_tds": 0.6, "WR/receiving_yards": 0.7257711627494392, "WR/receptions": 0.75642965204236}
GLM correction (var_inflation): {"QB/interceptions": 1.11, "QB/passing_tds": 0.93, "QB/passing_yards": 1.06, "RB/rushing_tds": 1.11, "RB/rushing_yards": 1.3, "TE/receiving_tds": 0.93, "TE/receiving_yards": 1.23, "TE/receptions": 1.3, "WR/receiving_tds": 0.93, "WR/receiving_yards": 1.24, "WR/receptions": 1.08}
post-correction baseline: obj=2.699 mae=4.70 |bias|=0.48 boom_err=0.045 bust_err=0.081 rank=0.621 realism=0.00
    QB:mae6.5/bias+0.4/max26/boom0.11v0.14 | RB:mae4.6/bias+0.0/max25/boom0.06v0.08 | WR:mae4.1/bias-0.8/max20/boom0.03v0.07 | TE:mae3.6/bias-0.7/max17/boom0.05v0.11

### Phase 1 — coarse grid
phase-1 best (bw=0.15 yc=1.0 cap=1.25 cvf=0.7): obj=2.577 mae=4.69 |bias|=0.46 boom_err=0.040 bust_err=0.077 rank=0.623 realism=0.00
    QB:mae6.4/bias+0.6/max28/boom0.14v0.14 | RB:mae4.6/bias+0.3/max25/boom0.07v0.08 | WR:mae4.1/bias-0.6/max21/boom0.04v0.07 | TE:mae3.6/bias-0.4/max19/boom0.06v0.11

### Phase 2 — coordinate descent
pass 1: obj=2.497 mae=4.68 |bias|=0.45 boom_err=0.036 bust_err=0.077 rank=0.627 realism=0.00
    QB:mae6.4/bias+0.6/max27/boom0.14v0.14 | RB:mae4.6/bias+0.2/max26/boom0.07v0.08 | WR:mae4.1/bias-0.6/max21/boom0.04v0.07 | TE:mae3.6/bias-0.4/max18/boom0.06v0.11
pass 2: obj=2.390 mae=4.68 |bias|=0.42 boom_err=0.032 bust_err=0.075 rank=0.630 realism=0.00
    QB:mae6.4/bias+0.6/max27/boom0.14v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.5/max21/boom0.04v0.07 | TE:mae3.6/bias-0.3/max18/boom0.07v0.11
pass 3: obj=2.302 mae=4.68 |bias|=0.41 boom_err=0.028 bust_err=0.073 rank=0.632 realism=0.00
    QB:mae6.4/bias+0.6/max27/boom0.15v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.5/max22/boom0.05v0.07 | TE:mae3.6/bias-0.3/max19/boom0.07v0.11
pass 4: obj=2.258 mae=4.67 |bias|=0.40 boom_err=0.028 bust_err=0.071 rank=0.634 realism=0.00
    QB:mae6.4/bias+0.6/max27/boom0.15v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.4/max21/boom0.05v0.07 | TE:mae3.6/bias-0.3/max19/boom0.07v0.11

### Phase 3 — random local polish
phase-3 best: obj=2.169 mae=4.67 |bias|=0.36 boom_err=0.027 bust_err=0.070 rank=0.636 realism=0.00
    QB:mae6.3/bias+0.6/max27/boom0.14v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.3/max22/boom0.05v0.07 | TE:mae3.6/bias-0.2/max19/boom0.07v0.11

## FINAL
```json
{
  "context_clamp_hi": 1.1802847303503634,
  "context_clamp_lo": 0.8670117490120338,
  "count_cv": 0.956158502626832,
  "cv_floor_frac": 0.9936043290168576,
  "depth_chart_damping": 0.5,
  "factor_strength": {
    "coaching": 0.38096369178881806,
    "depth_chart": 0.0,
    "game_environment": 0.6259471048178445,
    "game_script": 1.2560026105913686,
    "market": 0.7164282137335403,
    "news": 0.944439598133239,
    "opponent_matchup": 1.163138576323756,
    "position_group_form": 0.4506466796487866,
    "qb_support": 1.4404728301628915,
    "rest": 0.584961292368502,
    "usage_trend": 0.7554800859783712,
    "weather": 0.8849412664068633
  },
  "glm_bias": {
    "QB/interceptions": 0.6,
    "QB/passing_tds": 0.7646582742085342,
    "QB/passing_yards": 0.9756218366009062,
    "RB/rushing_tds": 0.6,
    "RB/rushing_yards": 0.8507475129809026,
    "TE/receiving_tds": 0.6,
    "TE/receiving_yards": 0.6,
    "TE/receptions": 0.8216926869350862,
    "WR/receiving_tds": 0.6,
    "WR/receiving_yards": 0.7257711627494392,
    "WR/receptions": 0.75642965204236
  },
  "glm_blend_weight": 0.05,
  "glm_var_inflation": {
    "QB/interceptions": 1.11,
    "QB/passing_tds": 0.93,
    "QB/passing_yards": 1.06,
    "RB/rushing_tds": 1.11,
    "RB/rushing_yards": 1.3,
    "TE/receiving_tds": 0.93,
    "TE/receiving_yards": 1.23,
    "TE/receptions": 1.3,
    "WR/receiving_tds": 0.93,
    "WR/receiving_yards": 1.24,
    "WR/receptions": 1.08
  },
  "market_clamp_hi": 1.6,
  "market_clamp_lo": 0.6,
  "offense_stack_cap": 1.28,
  "role_change_retention": 0.45,
  "rookie_cv_inflation": 1.35,
  "stat_mean_hi": 1.483909251659889,
  "stat_mean_lo": 0.45,
  "yard_cv": 0.7838662613468151
}
```
final metrics:
```json
{
  "objective": 2.168522165706868,
  "mae": 4.67009056316889,
  "bias_abs": 0.36139320137887854,
  "boom_calib_err": 0.02686973861469922,
  "bust_calib_err": 0.06985325574445139,
  "realism_penalty": 0.0,
  "rank_corr": 0.6362403590672573,
  "n": 2740,
  "per_position": {
    "QB": {
      "n": 641,
      "mae": 6.3443845430854005,
      "bias": 0.551586433144534,
      "boom_calib_err": 0.01718147469466785,
      "bust_calib_err": 0.1002471656650298,
      "realism_penalty": 0.0,
      "rank_corr": 0.5104823842848671,
      "max_proj": 26.795347356075695,
      "pred_boom_rate": 0.13967537936755148,
      "actual_boom_rate": 0.1372854914196568
    },
    "RB": {
      "n": 700,
      "mae": 4.574221465344547,
      "bias": 0.3232200613626277,
      "boom_calib_err": 0.018112657902440203,
      "bust_calib_err": 0.0437011925657836,
      "realism_penalty": 0.0,
      "rank_corr": 0.73448450001462,
      "max_proj": 25.84688648451067,
      "pred_boom_rate": 0.07018203568336237,
      "actual_boom_rate": 0.08428571428571428
    },
    "WR": {
      "n": 700,
      "mae": 4.1144652807907,
      "bias": -0.34571701927808357,
      "boom_calib_err": 0.025740663042102103,
      "bust_calib_err": 0.09858855122885911,
      "realism_penalty": 0.0,
      "rank_corr": 0.6606972583496556,
      "max_proj": 21.782439056635944,
      "pred_boom_rate": 0.046041403099146366,
      "actual_boom_rate": 0.06857142857142857
    },
    "TE": {
      "n": 699,
      "mae": 3.6472909634549135,
      "bias": -0.22504929173026897,
      "boom_calib_err": 0.04644415881958673,
      "bust_calib_err": 0.036876113518133094,
      "realism_penalty": 0.0,
      "rank_corr": 0.6392972936198862,
      "max_proj": 18.845811206202,
      "pred_boom_rate": 0.06805374556637941,
      "actual_boom_rate": 0.10872675250357654
    }
  }
}
```

written -> models\fantasy_calibration.json
- validate_new_knobs (analytic vs real trailing+depth_chart): max relative mean-FP error = 0.00006 (rookie_cv_high row=46 (WR), n=20 rows x 5 perturbations)

## Sweep run
GLM correction (bias): {"QB/interceptions": 0.6, "QB/passing_tds": 0.7646582742085342, "QB/passing_yards": 0.9756218366009062, "RB/rushing_tds": 0.6, "RB/rushing_yards": 0.8507475129809026, "TE/receiving_tds": 0.6, "TE/receiving_yards": 0.6, "TE/receptions": 0.8216926869350862, "WR/receiving_tds": 0.6, "WR/receiving_yards": 0.7257711627494392, "WR/receptions": 0.75642965204236}
GLM correction (var_inflation): {"QB/interceptions": 1.11, "QB/passing_tds": 0.93, "QB/passing_yards": 1.06, "RB/rushing_tds": 1.11, "RB/rushing_yards": 1.3, "TE/receiving_tds": 0.93, "TE/receiving_yards": 1.23, "TE/receptions": 1.3, "WR/receiving_tds": 0.93, "WR/receiving_yards": 1.24, "WR/receptions": 1.08}
post-correction baseline: obj=2.708 mae=4.70 |bias|=0.48 boom_err=0.044 bust_err=0.082 rank=0.618 realism=0.00
    QB:mae6.5/bias+0.4/max26/boom0.11v0.14 | RB:mae4.6/bias+0.1/max25/boom0.06v0.08 | WR:mae4.1/bias-0.8/max20/boom0.03v0.07 | TE:mae3.6/bias-0.6/max17/boom0.05v0.11
- validate_new_knobs (analytic vs real trailing+depth_chart): max relative mean-FP error = 0.00006 (retention_high row=2352 (WR), n=40 rows x 5 perturbations)

### Phase 1 — coarse grid
phase-1 best (bw=0.15 yc=1.0 cap=1.25 cvf=0.7): obj=2.588 mae=4.69 |bias|=0.46 boom_err=0.040 bust_err=0.079 rank=0.622 realism=0.00
    QB:mae6.4/bias+0.6/max28/boom0.13v0.14 | RB:mae4.6/bias+0.2/max25/boom0.07v0.08 | WR:mae4.1/bias-0.6/max21/boom0.04v0.07 | TE:mae3.6/bias-0.4/max19/boom0.06v0.11

### Phase 1b — coarse grid on role-context knobs
phase-1b best (dcd=0.0 rcr=1.0 rci=3.0): obj=2.335 mae=4.69 |bias|=0.34 boom_err=0.038 bust_err=0.077 rank=0.629 realism=0.00
    QB:mae6.4/bias+0.4/max28/boom0.13v0.14 | RB:mae4.6/bias+0.1/max25/boom0.06v0.08 | WR:mae4.1/bias-0.4/max21/boom0.04v0.07 | TE:mae3.7/bias-0.4/max19/boom0.06v0.11

### Phase 2 — coordinate descent
pass 1: obj=2.250 mae=4.68 |bias|=0.33 boom_err=0.033 bust_err=0.074 rank=0.630 realism=0.00
    QB:mae6.4/bias+0.4/max27/boom0.14v0.14 | RB:mae4.6/bias+0.1/max26/boom0.07v0.08 | WR:mae4.1/bias-0.4/max20/boom0.05v0.07 | TE:mae3.7/bias-0.4/max19/boom0.06v0.11
pass 2: obj=2.164 mae=4.67 |bias|=0.31 boom_err=0.027 bust_err=0.074 rank=0.631 realism=0.00
    QB:mae6.4/bias+0.4/max27/boom0.14v0.14 | RB:mae4.6/bias+0.1/max26/boom0.07v0.08 | WR:mae4.1/bias-0.3/max21/boom0.05v0.07 | TE:mae3.7/bias-0.4/max20/boom0.07v0.11
pass 3: obj=2.155 mae=4.68 |bias|=0.31 boom_err=0.027 bust_err=0.074 rank=0.631 realism=0.00
    QB:mae6.4/bias+0.4/max27/boom0.14v0.14 | RB:mae4.6/bias+0.2/max26/boom0.07v0.08 | WR:mae4.1/bias-0.3/max21/boom0.05v0.07 | TE:mae3.7/bias-0.3/max19/boom0.07v0.11
pass 4: obj=2.123 mae=4.67 |bias|=0.30 boom_err=0.026 bust_err=0.074 rank=0.632 realism=0.00
    QB:mae6.4/bias+0.5/max27/boom0.15v0.14 | RB:mae4.6/bias+0.2/max26/boom0.07v0.08 | WR:mae4.1/bias-0.2/max22/boom0.05v0.07 | TE:mae3.7/bias-0.3/max19/boom0.07v0.11

### Phase 3 — random local polish
phase-3 best: obj=2.069 mae=4.66 |bias|=0.32 boom_err=0.024 bust_err=0.069 rank=0.635 realism=0.00
    QB:mae6.4/bias+0.5/max27/boom0.15v0.14 | RB:mae4.5/bias+0.3/max26/boom0.08v0.08 | WR:mae4.1/bias-0.2/max22/boom0.05v0.07 | TE:mae3.7/bias-0.2/max19/boom0.07v0.11

## FINAL
```json
{
  "context_clamp_hi": 1.1766099746597223,
  "context_clamp_lo": 0.9007308499634897,
  "count_cv": 1.0681584072812569,
  "cv_floor_frac": 1.0,
  "depth_chart_damping": 0.0,
  "factor_strength": {
    "coaching": 0.6711451175385926,
    "depth_chart": 0.9433072462461046,
    "game_environment": 0.656223982967629,
    "game_script": 0.7805269378680559,
    "market": 0.8395551798708143,
    "news": 1.1808596216874032,
    "opponent_matchup": 1.2938842323402566,
    "position_group_form": 0.5429612772881289,
    "qb_support": 1.4248305149678746,
    "rest": 0.8041546997696467,
    "usage_trend": 0.7088226288584423,
    "weather": 0.9999001124684316
  },
  "glm_bias": {
    "QB/interceptions": 0.6,
    "QB/passing_tds": 0.7646582742085342,
    "QB/passing_yards": 0.9756218366009062,
    "RB/rushing_tds": 0.6,
    "RB/rushing_yards": 0.8507475129809026,
    "TE/receiving_tds": 0.6,
    "TE/receiving_yards": 0.6,
    "TE/receptions": 0.8216926869350862,
    "WR/receiving_tds": 0.6,
    "WR/receiving_yards": 0.7257711627494392,
    "WR/receptions": 0.75642965204236
  },
  "glm_blend_weight": 0.05,
  "glm_var_inflation": {
    "QB/interceptions": 1.11,
    "QB/passing_tds": 0.93,
    "QB/passing_yards": 1.06,
    "RB/rushing_tds": 1.11,
    "RB/rushing_yards": 1.3,
    "TE/receiving_tds": 0.93,
    "TE/receiving_yards": 1.23,
    "TE/receptions": 1.3,
    "WR/receiving_tds": 0.93,
    "WR/receiving_yards": 1.24,
    "WR/receptions": 1.08
  },
  "market_clamp_hi": 1.6,
  "market_clamp_lo": 0.6,
  "offense_stack_cap": 1.2457500613633745,
  "role_change_retention": 0.9564728741092494,
  "rookie_cv_inflation": 3.0,
  "stat_mean_hi": 1.687162828380909,
  "stat_mean_lo": 0.3,
  "yard_cv": 0.9909474962641236
}
```
final metrics:
```json
{
  "objective": 2.0686467179800667,
  "mae": 4.663657200417699,
  "bias_abs": 0.31952585850375326,
  "boom_calib_err": 0.02359776087032258,
  "bust_calib_err": 0.06852083726534154,
  "realism_penalty": 0.0,
  "rank_corr": 0.635208009213096,
  "n": 2741,
  "per_position": {
    "QB": {
      "n": 641,
      "mae": 6.35241488841772,
      "bias": 0.5422735572191262,
      "boom_calib_err": 0.01818504179738546,
      "bust_calib_err": 0.1197291998169749,
      "realism_penalty": 0.0,
      "rank_corr": 0.511810932427067,
      "max_proj": 27.00079539324778,
      "pred_boom_rate": 0.149803999152558,
      "actual_boom_rate": 0.1372854914196568
    },
    "RB": {
      "n": 700,
      "mae": 4.546490491873332,
      "bias": 0.2665776151191879,
      "boom_calib_err": 0.01616039291262334,
      "bust_calib_err": 0.035655796598155265,
      "realism_penalty": 0.0,
      "rank_corr": 0.73104623593699,
      "max_proj": 26.127592397417743,
      "pred_boom_rate": 0.07501828717552698,
      "actual_boom_rate": 0.08428571428571428
    },
    "WR": {
      "n": 700,
      "mae": 4.103752347272719,
      "bias": -0.22583529204726419,
      "boom_calib_err": 0.016613646783332107,
      "bust_calib_err": 0.08316919989500919,
      "realism_penalty": 0.0,
      "rank_corr": 0.6626290873272144,
      "max_proj": 21.957747895854368,
      "pred_boom_rate": 0.05270078980884324,
      "actual_boom_rate": 0.06857142857142857
    },
    "TE": {
      "n": 700,
      "mae": 3.6519710741070277,
      "bias": -0.24341696962943477,
      "boom_calib_err": 0.04343196198794943,
      "bust_calib_err": 0.03552915275122682,
      "realism_penalty": 0.0,
      "rank_corr": 0.6353457811611123,
      "max_proj": 18.78713574409196,
      "pred_boom_rate": 0.07305165164742819,
      "actual_boom_rate": 0.10857142857142857
    }
  }
}
```

written -> models\fantasy_calibration.json


<!-- A sweep run attempting to make bias-compliance a hard per-candidate constraint throughout phases 1-3 is intentionally omitted here: it got stuck at the unmodified post-correction baseline (phase 1 alone never reaches compliance, so a strict per-candidate gate rejects every early move) and was superseded by the Phase 4 gate-compliance-polish approach in the run below. -->
## Sweep run
GLM correction (bias): {"QB/interceptions": 0.6, "QB/passing_tds": 0.7646582742085342, "QB/passing_yards": 0.9756218366009062, "RB/rushing_tds": 0.6, "RB/rushing_yards": 0.8507475129809026, "TE/receiving_tds": 0.6, "TE/receiving_yards": 0.6, "TE/receptions": 0.8216926869350862, "WR/receiving_tds": 0.6, "WR/receiving_yards": 0.7257711627494392, "WR/receptions": 0.75642965204236}
GLM correction (var_inflation): {"QB/interceptions": 1.11, "QB/passing_tds": 0.93, "QB/passing_yards": 1.06, "RB/rushing_tds": 1.11, "RB/rushing_yards": 1.3, "TE/receiving_tds": 0.93, "TE/receiving_yards": 1.23, "TE/receptions": 1.3, "WR/receiving_tds": 0.93, "WR/receiving_yards": 1.24, "WR/receptions": 1.08}
gate_bias_max (verify_fantasy_calibration.py's own bound): 0.317495
post-correction baseline: obj=2.708 mae=4.70 |bias|=0.48 boom_err=0.044 bust_err=0.082 rank=0.618 realism=0.00
    QB:mae6.5/bias+0.4/max26/boom0.11v0.14 | RB:mae4.6/bias+0.1/max25/boom0.06v0.08 | WR:mae4.1/bias-0.8/max20/boom0.03v0.07 | TE:mae3.6/bias-0.6/max17/boom0.05v0.11
- validate_new_knobs (analytic vs real trailing+depth_chart): max relative mean-FP error = 0.00006 (retention_high row=2352 (WR), n=40 rows x 5 perturbations)

### Phase 1 — coarse grid
phase-1 best (bw=0.15 yc=1.0 cap=1.25 cvf=0.7): obj=2.588 mae=4.69 |bias|=0.46 boom_err=0.040 bust_err=0.079 rank=0.622 realism=0.00
    QB:mae6.4/bias+0.6/max28/boom0.13v0.14 | RB:mae4.6/bias+0.2/max25/boom0.07v0.08 | WR:mae4.1/bias-0.6/max21/boom0.04v0.07 | TE:mae3.6/bias-0.4/max19/boom0.06v0.11

### Phase 1b — coarse grid on role-context knobs
phase-1b best (dcd=0.0 rcr=1.0 rci=3.0): obj=2.335 mae=4.69 |bias|=0.34 boom_err=0.038 bust_err=0.077 rank=0.629 realism=0.00
    QB:mae6.4/bias+0.4/max28/boom0.13v0.14 | RB:mae4.6/bias+0.1/max25/boom0.06v0.08 | WR:mae4.1/bias-0.4/max21/boom0.04v0.07 | TE:mae3.7/bias-0.4/max19/boom0.06v0.11

### Phase 2 — coordinate descent
pass 1: obj=2.250 mae=4.68 |bias|=0.33 boom_err=0.033 bust_err=0.074 rank=0.630 realism=0.00
    QB:mae6.4/bias+0.4/max27/boom0.14v0.14 | RB:mae4.6/bias+0.1/max26/boom0.07v0.08 | WR:mae4.1/bias-0.4/max20/boom0.05v0.07 | TE:mae3.7/bias-0.4/max19/boom0.06v0.11
pass 2: obj=2.164 mae=4.67 |bias|=0.31 boom_err=0.027 bust_err=0.074 rank=0.631 realism=0.00
    QB:mae6.4/bias+0.4/max27/boom0.14v0.14 | RB:mae4.6/bias+0.1/max26/boom0.07v0.08 | WR:mae4.1/bias-0.3/max21/boom0.05v0.07 | TE:mae3.7/bias-0.4/max20/boom0.07v0.11
pass 3: obj=2.155 mae=4.68 |bias|=0.31 boom_err=0.027 bust_err=0.074 rank=0.631 realism=0.00
    QB:mae6.4/bias+0.4/max27/boom0.14v0.14 | RB:mae4.6/bias+0.2/max26/boom0.07v0.08 | WR:mae4.1/bias-0.3/max21/boom0.05v0.07 | TE:mae3.7/bias-0.3/max19/boom0.07v0.11
pass 4: obj=2.123 mae=4.67 |bias|=0.30 boom_err=0.026 bust_err=0.074 rank=0.632 realism=0.00
    QB:mae6.4/bias+0.5/max27/boom0.15v0.14 | RB:mae4.6/bias+0.2/max26/boom0.07v0.08 | WR:mae4.1/bias-0.2/max22/boom0.05v0.07 | TE:mae3.7/bias-0.3/max19/boom0.07v0.11

### Phase 3 — random local polish
phase-3 best: obj=2.069 mae=4.66 |bias|=0.32 boom_err=0.024 bust_err=0.069 rank=0.635 realism=0.00
    QB:mae6.4/bias+0.5/max27/boom0.15v0.14 | RB:mae4.5/bias+0.3/max26/boom0.08v0.08 | WR:mae4.1/bias-0.2/max22/boom0.05v0.07 | TE:mae3.7/bias-0.2/max19/boom0.07v0.11

### Phase 4 — gate-compliance polish (phase-3 |bias|=0.3195 > gate 0.3175)
phase-4 best (gate-compliant): obj=2.045 mae=4.67 |bias|=0.30 boom_err=0.022 bust_err=0.069 rank=0.634 realism=0.00
    QB:mae6.4/bias+0.5/max27/boom0.15v0.14 | RB:mae4.5/bias+0.2/max26/boom0.07v0.08 | WR:mae4.1/bias-0.2/max22/boom0.05v0.07 | TE:mae3.7/bias-0.2/max19/boom0.07v0.11

## FINAL
```json
{
  "context_clamp_hi": 1.2032328109924217,
  "context_clamp_lo": 0.8757616083311158,
  "count_cv": 1.111063348382487,
  "cv_floor_frac": 1.0,
  "depth_chart_damping": 0.0,
  "factor_strength": {
    "coaching": 0.5987404113889538,
    "depth_chart": 1.051324285057015,
    "game_environment": 0.5898593352390663,
    "game_script": 0.5284267711108595,
    "market": 0.9682140775860162,
    "news": 0.9630332831734955,
    "opponent_matchup": 1.3763987886100024,
    "position_group_form": 0.5177033906935693,
    "qb_support": 1.5,
    "rest": 0.7779501243294177,
    "usage_trend": 0.7380620686387123,
    "weather": 1.2341851200618204
  },
  "glm_bias": {
    "QB/interceptions": 0.6,
    "QB/passing_tds": 0.7646582742085342,
    "QB/passing_yards": 0.9756218366009062,
    "RB/rushing_tds": 0.6,
    "RB/rushing_yards": 0.8507475129809026,
    "TE/receiving_tds": 0.6,
    "TE/receiving_yards": 0.6,
    "TE/receptions": 0.8216926869350862,
    "WR/receiving_tds": 0.6,
    "WR/receiving_yards": 0.7257711627494392,
    "WR/receptions": 0.75642965204236
  },
  "glm_blend_weight": 0.05,
  "glm_var_inflation": {
    "QB/interceptions": 1.11,
    "QB/passing_tds": 0.93,
    "QB/passing_yards": 1.06,
    "RB/rushing_tds": 1.11,
    "RB/rushing_yards": 1.3,
    "TE/receiving_tds": 0.93,
    "TE/receiving_yards": 1.23,
    "TE/receptions": 1.3,
    "WR/receiving_tds": 0.93,
    "WR/receiving_yards": 1.24,
    "WR/receptions": 1.08
  },
  "market_clamp_hi": 1.6,
  "market_clamp_lo": 0.6,
  "offense_stack_cap": 1.28,
  "role_change_retention": 0.9648121939964304,
  "rookie_cv_inflation": 3.0,
  "stat_mean_hi": 1.6668136325626661,
  "stat_mean_lo": 0.3,
  "yard_cv": 0.980690368911579
}
```
final metrics:
```json
{
  "objective": 2.0447374333536743,
  "mae": 4.666616045128498,
  "bias_abs": 0.30118479204152687,
  "boom_calib_err": 0.021894606352086,
  "bust_calib_err": 0.06936902782055561,
  "realism_penalty": 0.0,
  "rank_corr": 0.633960812203041,
  "n": 2741,
  "per_position": {
    "QB": {
      "n": 641,
      "mae": 6.35713688551115,
      "bias": 0.5019434778880963,
      "boom_calib_err": 0.015876346745944653,
      "bust_calib_err": 0.12213745945856333,
      "realism_penalty": 0.0,
      "rank_corr": 0.510176565565439,
      "max_proj": 26.937009063504885,
      "pred_boom_rate": 0.14918993263216182,
      "actual_boom_rate": 0.1372854914196568
    },
    "RB": {
      "n": 700,
      "mae": 4.541956467955728,
      "bias": 0.23855058750797167,
      "boom_calib_err": 0.01615616907992781,
      "bust_calib_err": 0.03816382067073614,
      "realism_penalty": 0.0,
      "rank_corr": 0.7301789098157297,
      "max_proj": 26.47715329707509,
      "pred_boom_rate": 0.0744685730416541,
      "actual_boom_rate": 0.08428571428571428
    },
    "WR": {
      "n": 700,
      "mae": 4.108734649777396,
      "bias": -0.21918048429977838,
      "boom_calib_err": 0.01664426330762127,
      "bust_calib_err": 0.08326372156432107,
      "realism_penalty": 0.0,
      "rank_corr": 0.6611062232642548,
      "max_proj": 22.176101127027625,
      "pred_boom_rate": 0.05321386613657492,
      "actual_boom_rate": 0.06857142857142857
    },
    "TE": {
      "n": 700,
      "mae": 3.6586361772697176,
      "bias": -0.24506461847026126,
      "boom_calib_err": 0.038901646274850266,
      "bust_calib_err": 0.03391110958860188,
      "realism_penalty": 0.0,
      "rank_corr": 0.6343815501667405,
      "max_proj": 19.212227193975185,
      "pred_boom_rate": 0.07355530238572058,
      "actual_boom_rate": 0.10857142857142857
    }
  }
}
```

written -> models\fantasy_calibration.json

## Sweep run
GLM correction (bias): {"QB/interceptions": 0.6, "QB/passing_tds": 0.7646582742085342, "QB/passing_yards": 0.9756218366009062, "RB/rushing_tds": 0.6, "RB/rushing_yards": 0.8507475129809026, "TE/receiving_tds": 0.6, "TE/receiving_yards": 0.6, "TE/receptions": 0.8216926869350862, "WR/receiving_tds": 0.6, "WR/receiving_yards": 0.7257711627494392, "WR/receptions": 0.75642965204236}
GLM correction (var_inflation): {"QB/interceptions": 1.11, "QB/passing_tds": 0.93, "QB/passing_yards": 1.06, "RB/rushing_tds": 1.11, "RB/rushing_yards": 1.3, "TE/receiving_tds": 0.93, "TE/receiving_yards": 1.23, "TE/receptions": 1.3, "WR/receiving_tds": 0.93, "WR/receiving_yards": 1.24, "WR/receptions": 1.08}
gate_bias_max (verify_fantasy_calibration.py's own bound): 0.431463
post-correction baseline: obj=2.741 mae=4.68 |bias|=0.56 boom_err=0.042 bust_err=0.077 rank=0.622 realism=0.00
    QB:mae6.4/bias+0.8/max27/boom0.12v0.14 | RB:mae4.6/bias+0.2/max25/boom0.06v0.08 | WR:mae4.1/bias-0.7/max20/boom0.03v0.07 | TE:mae3.7/bias-0.5/max17/boom0.05v0.11
- validate_new_knobs (analytic vs real trailing+depth_chart): max relative mean-FP error = 0.00006 (rookie_cv_high row=2352 (WR), n=40 rows x 5 perturbations)

### Phase 1 — coarse grid
phase-1 best (bw=0.15 yc=1.0 cap=1.25 cvf=0.7): obj=2.684 mae=4.69 |bias|=0.56 boom_err=0.038 bust_err=0.073 rank=0.622 realism=0.00
    QB:mae6.4/bias+1.0/max28/boom0.15v0.14 | RB:mae4.6/bias+0.4/max26/boom0.07v0.08 | WR:mae4.1/bias-0.6/max21/boom0.04v0.07 | TE:mae3.7/bias-0.3/max19/boom0.06v0.11

### Phase 1b — coarse grid on role-context knobs
phase-1b best (dcd=0.0 rcr=0.65 rci=3.0): obj=2.369 mae=4.66 |bias|=0.44 boom_err=0.039 bust_err=0.069 rank=0.635 realism=0.00
    QB:mae6.3/bias+0.7/max28/boom0.14v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.4/max21/boom0.04v0.07 | TE:mae3.7/bias-0.4/max19/boom0.06v0.11

### Phase 2 — coordinate descent
pass 1: obj=2.254 mae=4.66 |bias|=0.43 boom_err=0.030 bust_err=0.067 rank=0.636 realism=0.00
    QB:mae6.3/bias+0.7/max28/boom0.15v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.4/max21/boom0.05v0.07 | TE:mae3.7/bias-0.3/max19/boom0.07v0.11
pass 2: obj=2.230 mae=4.66 |bias|=0.42 boom_err=0.028 bust_err=0.067 rank=0.636 realism=0.00
    QB:mae6.3/bias+0.8/max28/boom0.15v0.14 | RB:mae4.6/bias+0.3/max26/boom0.07v0.08 | WR:mae4.1/bias-0.3/max22/boom0.05v0.07 | TE:mae3.7/bias-0.3/max19/boom0.07v0.11
pass 3: obj=2.210 mae=4.65 |bias|=0.42 boom_err=0.028 bust_err=0.065 rank=0.636 realism=0.00
    QB:mae6.3/bias+0.8/max28/boom0.15v0.14 | RB:mae4.6/bias+0.3/max27/boom0.07v0.08 | WR:mae4.1/bias-0.3/max22/boom0.05v0.07 | TE:mae3.7/bias-0.3/max20/boom0.07v0.11
pass 4: obj=2.204 mae=4.65 |bias|=0.41 boom_err=0.029 bust_err=0.065 rank=0.636 realism=0.00
    QB:mae6.3/bias+0.7/max28/boom0.15v0.14 | RB:mae4.6/bias+0.3/max27/boom0.07v0.08 | WR:mae4.1/bias-0.4/max22/boom0.05v0.07 | TE:mae3.7/bias-0.3/max20/boom0.07v0.11

### Phase 3 — random local polish
phase-3 best: obj=2.184 mae=4.66 |bias|=0.40 boom_err=0.026 bust_err=0.067 rank=0.636 realism=0.00
    QB:mae6.3/bias+0.8/max28/boom0.15v0.14 | RB:mae4.6/bias+0.3/max27/boom0.07v0.08 | WR:mae4.1/bias-0.3/max22/boom0.05v0.07 | TE:mae3.7/bias-0.2/max20/boom0.07v0.11

## FINAL
```json
{
  "context_clamp_hi": 1.2597304347237888,
  "context_clamp_lo": 0.8108835000583887,
  "count_cv": 1.3,
  "cv_floor_frac": 0.8521541335360823,
  "depth_chart_damping": 0.0,
  "factor_strength": {
    "coaching": 0.7872268805754122,
    "depth_chart": 0.8991241884594573,
    "game_environment": 1.0646771439168317,
    "game_script": 0.8179856274010556,
    "market": 1.1505418111431491,
    "news": 0.7246628183789607,
    "opponent_matchup": 1.071103411500277,
    "position_group_form": 0.8925135444458586,
    "qb_support": 1.4971685377017143,
    "rest": 0.9392529630619791,
    "usage_trend": 0.6886953621359637,
    "weather": 1.0179164361012893
  },
  "glm_bias": {
    "QB/interceptions": 0.6,
    "QB/passing_tds": 0.7646582742085342,
    "QB/passing_yards": 0.9756218366009062,
    "RB/rushing_tds": 0.6,
    "RB/rushing_yards": 0.8507475129809026,
    "TE/receiving_tds": 0.6,
    "TE/receiving_yards": 0.6,
    "TE/receptions": 0.8216926869350862,
    "WR/receiving_tds": 0.6,
    "WR/receiving_yards": 0.7257711627494392,
    "WR/receptions": 0.75642965204236
  },
  "glm_blend_weight": 0.07715949622952932,
  "glm_var_inflation": {
    "QB/interceptions": 1.11,
    "QB/passing_tds": 0.93,
    "QB/passing_yards": 1.06,
    "RB/rushing_tds": 1.11,
    "RB/rushing_yards": 1.3,
    "TE/receiving_tds": 0.93,
    "TE/receiving_yards": 1.23,
    "TE/receptions": 1.3,
    "WR/receiving_tds": 0.93,
    "WR/receiving_yards": 1.24,
    "WR/receptions": 1.08
  },
  "market_clamp_hi": 1.6,
  "market_clamp_lo": 0.6,
  "offense_stack_cap": 1.28,
  "role_change_retention": 0.8412909741621974,
  "rookie_cv_inflation": 2.969928418038401,
  "stat_mean_hi": 1.5862317294546404,
  "stat_mean_lo": 0.3,
  "yard_cv": 0.9752000348938357
}
```
final metrics:
```json
{
  "objective": 2.1839284866889628,
  "mae": 4.657109488723508,
  "bias_abs": 0.4033544659456604,
  "boom_calib_err": 0.025629829485479025,
  "bust_calib_err": 0.06685677320039753,
  "realism_penalty": 0.0,
  "rank_corr": 0.6363509204066746,
  "n": 2741,
  "per_position": {
    "QB": {
      "n": 641,
      "mae": 6.3044647027846015,
      "bias": 0.7872403706689691,
      "boom_calib_err": 0.02440566063708852,
      "bust_calib_err": 0.10469867584638669,
      "realism_penalty": 0.0,
      "rank_corr": 0.5167463599460143,
      "max_proj": 27.887491055181428,
      "pred_boom_rate": 0.15039519391881692,
      "actual_boom_rate": 0.1372854914196568
    },
    "RB": {
      "n": 700,
      "mae": 4.555216077382154,
      "bias": 0.3201189914401578,
      "boom_calib_err": 0.020708084551327877,
      "bust_calib_err": 0.040444430235633856,
      "realism_penalty": 0.0,
      "rank_corr": 0.7351571181257545,
      "max_proj": 26.773253000434497,
      "pred_boom_rate": 0.07360727568358935,
      "actual_boom_rate": 0.08428571428571428
    },
    "WR": {
      "n": 700,
      "mae": 4.1095999418977565,
      "bias": -0.2851063380820539,
      "boom_calib_err": 0.018100547139852433,
      "bust_calib_err": 0.08795548787591352,
      "realism_penalty": 0.0,
      "rank_corr": 0.6571900157621853,
      "max_proj": 21.762954876656636,
      "pred_boom_rate": 0.05047088143157614,
      "actual_boom_rate": 0.06857142857142857
    },
    "TE": {
      "n": 700,
      "mae": 3.659157232829522,
      "bias": -0.22095216359146086,
      "boom_calib_err": 0.039305025613647265,
      "bust_calib_err": 0.034328498843656,
      "realism_penalty": 0.0,
      "rank_corr": 0.6363101877927442,
      "max_proj": 19.85984776209922,
      "pred_boom_rate": 0.07236230761502113,
      "actual_boom_rate": 0.10857142857142857
    }
  }
}
```

written -> models\fantasy_calibration.json

> 2026-09-17 re-run after the v0.9-m6 shrinkage and prop changes. Not adopted:
> `models/fantasy_calibration.json` was restored to the v0.9-m5.1 values above.
