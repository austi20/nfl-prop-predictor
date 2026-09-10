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
