"""Tune FantasyCalibration against the 2025 backtest cache. All four positions
are scored per-position-balanced (eval.fantasy_calibration.evaluate).

  uv run python scripts/tune_fantasy_calibration.py --build-cache
  uv run python scripts/tune_fantasy_calibration.py --validate-approx
  uv run python scripts/tune_fantasy_calibration.py --validate-new-knobs
  uv run python scripts/tune_fantasy_calibration.py --run
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.fantasy_calibration import (  # noqa: E402
    _BOOM,
    _BUST,
    _OFFENSE_SET,
    _YARDAGE,
    _apply_calib_to_row,
    _boom_bust_prob,
    build_eval_cache,
    default_calibration,
    evaluate,
    fit_glm_correction,
    load_eval_cache,
    save_calibration,
)

ARTIFACT = Path("models/fantasy_calibration.json")
CORRECTION = Path("models/fantasy_glm_correction.json")
LOG = Path("docs/fantasy_calibration_sweep.md")
_RANK_TOL = 0.03  # calibration must not drop within-position rank corr by more than this


def _load_or_fit_correction() -> tuple[dict, dict]:
    """The GLM bias/variance fit is deterministic (seed=11) but takes ~1h. Cache
    it to models/fantasy_glm_correction.json; delete that file to force a refit."""
    if CORRECTION.exists():
        d = json.loads(CORRECTION.read_text(encoding="utf-8"))
        return d["bias"], d["var_inflation"]
    bias, vinf = fit_glm_correction()
    CORRECTION.write_text(
        json.dumps({"bias": bias, "var_inflation": vinf}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return bias, vinf


def _log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")
    print(line)


def _summary(tag: str, m: dict) -> str:
    pp = " | ".join(
        f"{p}:mae{v['mae']:.1f}/bias{v['bias']:+.1f}/max{v['max_proj']:.0f}/boom{v['pred_boom_rate']:.2f}v{v['actual_boom_rate']:.2f}"
        for p, v in m["per_position"].items()
    )
    return (f"{tag}: obj={m['objective']:.3f} mae={m['mae']:.2f} |bias|={m['bias_abs']:.2f} "
            f"boom_err={m['boom_calib_err']:.3f} bust_err={m['bust_calib_err']:.3f} "
            f"rank={m['rank_corr']:.3f} realism={m['realism_penalty']:.2f}\n    {pp}")


def validate_approx(n: int = 200, seed: int = 3) -> float:
    """|analytic P(boom) - real 5000-sim MC P(boom)| on a subsample, using the
    genuine project_fantasy_points Monte Carlo over the real per-stat dists."""
    import warnings

    warnings.simplefilter("ignore")
    from eval.fantasy_points import project_fantasy_points
    from models.base import StatDistribution

    cache = load_eval_cache()
    calib = default_calibration()
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(cache["rows"]), size=min(n, len(cache["rows"])), replace=False)
    diffs = []
    for i in pick:
        r = cache["rows"][int(i)]
        pos = r["position"]
        # analytic P(boom)
        m, sd = _apply_calib_to_row(r, calib)
        p_analytic, _ = _boom_bust_prob(m, sd, _BOOM[pos], _BUST[pos])
        # real 5000-sim MC over the same per-stat blended dists (pre-context),
        # with context applied via stat_multipliers exactly like build_fantasy_summary
        dists: dict[str, StatDistribution] = {}
        for st in set(r["anchor"]) | set(r["glm"]):
            a = r["anchor"].get(st)
            g = r["glm"].get(st)
            if not a and not g:
                continue
            anchor_mean = a[0] if a else g[0]
            if g and g[0] > 0:
                blended = (1 - calib.glm_blend_weight) * (a[0] if a else 0.0) + calib.glm_blend_weight * g[0]
            else:
                blended = a[0] if a else 0.0
            ref = max(anchor_mean, 1e-6)
            blended = float(np.clip(blended, calib.stat_mean_lo * ref, calib.stat_mean_hi * ref))
            if blended <= 0:
                continue
            if g and g[0] > 0 and g[1] > 0:
                std, dt = g[1] * (blended / max(g[0], 1e-6)), g[2]
            else:
                cv = calib.yard_cv if st in _YARDAGE else calib.count_cv
                std, dt = cv * blended, ("gamma" if st in _YARDAGE else "poisson")
            dists[st] = StatDistribution(mean=blended, std=max(std, 1e-6), dist_type=dt)
        mult: dict[str, float] = {}
        offense: dict[str, float] = {}
        for name, mm, stats in r["factors"]:
            scaled = 1.0 + calib.strength(name) * (mm - 1.0)
            tgt = offense if name in _OFFENSE_SET else mult
            for s in stats:
                tgt[s] = tgt.get(s, 1.0) * scaled
        sm = {
            st: float(np.clip(mult.get(st, 1.0) * min(offense.get(st, 1.0), calib.offense_stack_cap),
                              calib.context_clamp_lo, calib.context_clamp_hi))
            for st in dists
        }
        proj = project_fantasy_points(dists, position=pos, scoring_mode="full_ppr",
                                      stat_multipliers=sm, seed=int(i), simulations=5000, calib=calib)
        diffs.append(abs(p_analytic - proj.boom_probability))
    mad = float(np.mean(diffs))
    _log(f"- approx validation (analytic vs real 5000-sim MC): mean |P(boom) diff| = {mad:.3f} (n={len(pick)})")
    return mad


def validate_new_knobs(n: int = 40, seed: int = 9) -> float:
    """Cross-check _apply_calib_to_row's analytic replay of the trailing blend
    and the depth-chart multiplier against the REAL production functions
    (_trailing_fantasy_distributions, _depth_chart_factor), each run under five
    calibrations that push role_change_retention / rookie_cv_inflation /
    depth_chart_damping far from default.

    This is the fidelity guarantee for sweeping those three knobs: evaluate()
    never re-fits a model, so `_apply_calib_to_row` re-derives their effect
    from cached raw ingredients (recent/base/n/rank_bucket/prior_bucket/
    depth_chart_ratio) rather than reapplying a frozen multiplier. Extracting
    _form_weight_for / _depth_chart_ratio means both sides call the same
    formula, but this comparison is the actual proof, not just an assumption
    that the extraction was done right. Returns the worst relative error
    across every (row, perturbed-calib) pair sampled.
    """
    import warnings

    warnings.simplefilter("ignore")
    from api.services.evaluation_service import scoring_weekly
    from api.services.fantasy_service import (
        _baselines_for,
        _depth_chart_factor,
        _positive_stats_for_position,
        _trailing_fantasy_distributions,
    )
    from api.settings import AppSettings
    from eval.fantasy_calibration import _fp_weights
    from models.base import StatDistribution

    cache = load_eval_cache()
    rows = cache["rows"]
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(rows), size=min(n, len(rows)), replace=False)
    settings = AppSettings(prewarm_fantasy_slate=False)
    weights = _fp_weights()

    # Each perturbation isolates one knob far from its default (0.45 / 1.35 /
    # 0.5) so a fidelity bug in that knob's path cannot hide near the default.
    perturbations = {
        "retention_low": default_calibration().replace(role_change_retention=0.10),
        "retention_high": default_calibration().replace(role_change_retention=0.95),
        "rookie_cv_high": default_calibration().replace(rookie_cv_inflation=3.0),
        "damping_full": default_calibration().replace(depth_chart_damping=1.0),
        "damping_low": default_calibration().replace(depth_chart_damping=0.05),
    }

    weekly_cache: dict[int, object] = {}
    baseline_cache: dict[int, dict] = {}
    worst_err = 0.0
    worst_tag = ""
    for i in pick:
        row = rows[int(i)]
        season, week, pos = row["season"], row["week"], row["position"]
        if season not in weekly_cache:
            weekly_cache[season] = scoring_weekly(settings, season)
            baseline_cache[season] = _baselines_for(weekly_cache[season])
        weekly = weekly_cache[season]
        baselines = baseline_cache[season]
        glm_dists = {
            st: StatDistribution(mean=m, std=s, dist_type=dt)
            for st, (m, s, dt) in row["glm"].items()
        }
        for tag, calib in perturbations.items():
            # Ground truth: the real trailing-anchor function, called with the
            # SAME buckets stored in the cache (bucket() is idempotent on its
            # own output, so feeding the bucket back in as the raw rank is
            # exact -- confirmed in docs/breakpoints/p8_evaluation.md).
            real_dists = _trailing_fantasy_distributions(
                weekly, player_id=row["player_id"], season=season, week=week,
                position=pos, model_distributions=glm_dists, calib=calib,
                depth_rank=row["rank_bucket"], prior_depth_rank=row["prior_bucket"],
            )
            depth_factor = _depth_chart_factor(
                baselines, position=pos, current=row["rank_bucket"],
                prior=row["prior_bucket"], calib=calib,
            )
            # Same "reapply the cached factor multiplier at this calib's
            # strength" fold-in _apply_calib_to_row uses for row["factors"] --
            # unchanged pre-existing logic, copied rather than imported only
            # because it's a local variable there. Confirmed identical result
            # in both places for every perturbation here, since none of them
            # touch factor_strength.
            mult: dict[str, float] = {}
            offense: dict[str, float] = {}
            for name, m, stats in row["factors"]:
                scaled = 1.0 + calib.strength(name) * (m - 1.0)
                tgt = offense if name in _OFFENSE_SET else mult
                for st in stats:
                    tgt[st] = tgt.get(st, 1.0) * scaled
            if depth_factor.applied:
                scaled = 1.0 + calib.strength("depth_chart") * (depth_factor.multiplier - 1.0)
                for st in _positive_stats_for_position(pos):
                    mult[st] = mult.get(st, 1.0) * scaled

            real_mean_fp = 0.0
            for st, dist in real_dists.items():
                w = weights.get(st, 0.0)
                if w == 0.0:
                    continue
                cm = float(np.clip(
                    mult.get(st, 1.0) * min(offense.get(st, 1.0), calib.offense_stack_cap),
                    calib.context_clamp_lo, calib.context_clamp_hi,
                ))
                real_mean_fp += w * dist.mean * cm

            analytic_mean_fp, _ = _apply_calib_to_row(row, calib)
            rel_err = abs(analytic_mean_fp - real_mean_fp) / max(abs(real_mean_fp), 1.0)
            if rel_err > worst_err:
                worst_err, worst_tag = rel_err, f"{tag} row={int(i)} ({pos})"

    _log(
        f"- validate_new_knobs (analytic vs real trailing+depth_chart): "
        f"max relative mean-FP error = {worst_err:.5f} ({worst_tag}, "
        f"n={len(pick)} rows x {len(perturbations)} perturbations)"
    )
    return worst_err


def _better(cand: dict, best: dict, base_rank: float) -> bool:
    return cand["objective"] < best["objective"] and cand["rank_corr"] >= base_rank - _RANK_TOL


def run() -> None:
    cache = load_eval_cache()
    base = default_calibration()
    # The uncalibrated baseline verify_fantasy_calibration.py's gate compares
    # against -- no glm_bias/var_inflation. Kept distinct from the
    # post-correction `base` below, which is the sweep's own search anchor.
    gate_bias_max = evaluate(base, cache)["bias_abs"] + 1e-6
    bias, vinf = _load_or_fit_correction()
    base = base.replace(glm_bias=bias, glm_var_inflation=vinf)
    base_m = evaluate(base, cache)
    base_rank = base_m["rank_corr"]
    _log("\n## Sweep run")
    _log(f"GLM correction (bias): {json.dumps(bias, sort_keys=True)}")
    _log(f"GLM correction (var_inflation): {json.dumps(vinf, sort_keys=True)}")
    _log(f"gate_bias_max (verify_fantasy_calibration.py's own bound): {gate_bias_max:.6f}")
    _log(_summary("post-correction baseline", base_m))

    # depth_chart_damping / role_change_retention / rookie_cv_inflation are
    # recomputed analytically from cached raw ingredients (see
    # _apply_calib_to_row's docstring), not reapplied on a frozen value like
    # the older knobs. Refuse to sweep them if that recompute doesn't match
    # the real production functions -- a silent drift here would tune toward
    # a model that isn't the one that ships. 1% relative mean-FP error is a
    # generous bar; the extraction this checks is exact math, not a fit.
    _FIDELITY_TOL = 0.01
    fidelity_err = validate_new_knobs()
    sweep_new_knobs = fidelity_err <= _FIDELITY_TOL
    if not sweep_new_knobs:
        _log(
            f"\n**WARNING: analytic/real fidelity check failed "
            f"({fidelity_err:.4f} > {_FIDELITY_TOL}) -- depth_chart_damping, "
            f"role_change_retention and rookie_cv_inflation will NOT be swept "
            f"this run. Investigate _apply_calib_to_row before re-running.**"
        )

    best_m, best_c = base_m, base

    # Phase 1: coarse grid on the highest-leverage axes
    _log("\n### Phase 1 — coarse grid")
    for bw, yc, cap, cvf in itertools.product(
        (0.10, 0.15, 0.20, 0.25, 0.30),
        (0.55, 0.70, 0.85, 1.00),
        (1.06, 1.10, 1.15, 1.25),
        (0.0, 0.4, 0.7),
    ):
        c = best_c.replace(glm_blend_weight=bw, yard_cv=yc, count_cv=max(yc + 0.15, 0.7),
                           offense_stack_cap=cap, cv_floor_frac=cvf)
        m = evaluate(c, cache)
        if _better(m, best_m, base_rank):
            best_m, best_c = m, c
    _log(_summary(f"phase-1 best (bw={best_c.glm_blend_weight} yc={best_c.yard_cv} "
                  f"cap={best_c.offense_stack_cap} cvf={best_c.cv_floor_frac})", best_m))

    # Phase 1b: coarse grid on the new role-context knobs, same idea as phase 1
    # but kept separate so a fidelity-check failure only skips this block.
    if sweep_new_knobs:
        _log("\n### Phase 1b — coarse grid on role-context knobs")
        for dcd, rcr, rci in itertools.product(
            (0.0, 0.25, 0.5, 0.75, 1.0),
            (0.05, 0.25, 0.45, 0.65, 0.85, 1.0),
            (1.0, 1.35, 1.75, 2.25, 3.0),
        ):
            c = best_c.replace(
                depth_chart_damping=dcd, role_change_retention=rcr, rookie_cv_inflation=rci,
            )
            m = evaluate(c, cache)
            if _better(m, best_m, base_rank):
                best_m, best_c = m, c
        _log(_summary(
            f"phase-1b best (dcd={best_c.depth_chart_damping} "
            f"rcr={best_c.role_change_retention} rci={best_c.rookie_cv_inflation})", best_m,
        ))

    # Phase 2: coordinate descent over every scalar
    _log("\n### Phase 2 — coordinate descent")
    axes = {
        "glm_blend_weight": (0.05, 0.40, 0.03),
        "stat_mean_hi": (1.10, 1.90, 0.10),
        "stat_mean_lo": (0.30, 0.60, 0.05),
        "yard_cv": (0.45, 1.20, 0.05),
        "count_cv": (0.55, 1.30, 0.05),
        "cv_floor_frac": (0.0, 1.0, 0.1),
        "context_clamp_hi": (1.08, 1.30, 0.02),
        "context_clamp_lo": (0.65, 0.92, 0.02),
        "offense_stack_cap": (1.03, 1.28, 0.02),
    }
    if sweep_new_knobs:
        axes.update({
            "depth_chart_damping": (0.0, 1.0, 0.05),
            "role_change_retention": (0.0, 1.0, 0.05),
            "rookie_cv_inflation": (1.0, 3.0, 0.1),
            # market_clamp_lo/hi are NOT swept: the eval cache carries zero
            # market factors (Kalshi only exposes currently-open markets, and
            # a finished 2025 season has none -- confirmed empty {} fetches),
            # so evaluate() would never see the market path fire and the sweep
            # would leave these at an arbitrary, untested value while implying
            # they'd been tuned. Left at their defaults until real quote
            # capture exists for a live/in-progress season.
        })
    for p in range(4):
        for name, (lo, hi, step) in axes.items():
            cur = getattr(best_c, name)
            for cand in (round(cur - step, 4), round(cur + step, 4)):
                if not (lo <= cand <= hi):
                    continue
                c = best_c.replace(**{name: cand})
                m = evaluate(c, cache)
                if _better(m, best_m, base_rank):
                    best_m, best_c = m, c
        for fname in list(best_c.factor_strength):
            cur = best_c.factor_strength[fname]
            for cand in (round(max(0.0, cur - 0.15), 3), round(min(1.5, cur + 0.15), 3)):
                fs = {**best_c.factor_strength, fname: cand}
                c = best_c.replace(factor_strength=fs)
                m = evaluate(c, cache)
                if _better(m, best_m, base_rank):
                    best_m, best_c = m, c
        _log(_summary(f"pass {p + 1}", best_m))

    # Phase 3: random local polish
    _log("\n### Phase 3 — random local polish")
    rng = np.random.default_rng(5)
    for _ in range(400):
        changes = dict(
            glm_blend_weight=float(np.clip(best_c.glm_blend_weight + rng.normal(0, 0.02), 0.05, 0.40)),
            yard_cv=float(np.clip(best_c.yard_cv + rng.normal(0, 0.04), 0.45, 1.20)),
            count_cv=float(np.clip(best_c.count_cv + rng.normal(0, 0.05), 0.55, 1.30)),
            cv_floor_frac=float(np.clip(best_c.cv_floor_frac + rng.normal(0, 0.06), 0.0, 1.0)),
            stat_mean_hi=float(np.clip(best_c.stat_mean_hi + rng.normal(0, 0.06), 1.10, 1.90)),
            offense_stack_cap=float(np.clip(best_c.offense_stack_cap + rng.normal(0, 0.02), 1.03, 1.28)),
            context_clamp_hi=float(np.clip(best_c.context_clamp_hi + rng.normal(0, 0.015), 1.08, 1.30)),
            context_clamp_lo=float(np.clip(best_c.context_clamp_lo + rng.normal(0, 0.015), 0.65, 0.92)),
            factor_strength={k: float(np.clip(v + rng.normal(0, 0.08), 0.0, 1.5))
                             for k, v in best_c.factor_strength.items()},
        )
        if sweep_new_knobs:
            changes.update(
                depth_chart_damping=float(np.clip(best_c.depth_chart_damping + rng.normal(0, 0.05), 0.0, 1.0)),
                role_change_retention=float(np.clip(best_c.role_change_retention + rng.normal(0, 0.05), 0.0, 1.0)),
                rookie_cv_inflation=float(np.clip(best_c.rookie_cv_inflation + rng.normal(0, 0.15), 1.0, 3.0)),
            )
        c = best_c.replace(**changes)
        m = evaluate(c, cache)
        if _better(m, best_m, base_rank):
            best_m, best_c = m, c
    _log(_summary("phase-3 best", best_m))

    # Phase 4: gate-compliance polish. Phase 3's optimum chases the composite
    # objective, which can leave |bias| a hair above the raw (uncalibrated)
    # baseline that scripts/verify_fantasy_calibration.py's gate compares
    # against -- exactly what happened the first time this ran: bias landed at
    # 0.320 against a 0.317 ceiling, a 0.002 miss.
    #
    # Enforcing bias-compliance as a hard constraint from Phase 1 onward was
    # tried and made things worse, not better: the very first Phase-1 grid
    # point already has bias ~0.46 (Phase 1 alone never reaches compliance --
    # that only emerges as an accumulated property of many axes moving
    # together in Phase 2+), so a strict per-candidate gate rejects every
    # early move and the whole search sticks at the unmodified defaults.
    #
    # This phase instead searches the LOCAL neighborhood of the already-good
    # Phase-3 optimum -- 0.002 away, not the whole space -- and requires
    # compliance only here. If nothing compliant turns up, `best_c` from
    # Phase 3 is kept as-is rather than silently degraded for no benefit.
    gate_ok = best_m["bias_abs"] <= gate_bias_max
    if not gate_ok:
        _log(
            f"\n### Phase 4 — gate-compliance polish "
            f"(phase-3 |bias|={best_m['bias_abs']:.4f} > gate {gate_bias_max:.4f})"
        )
        rng4 = np.random.default_rng(13)
        phase3_c, phase3_m = best_c, best_m
        for _ in range(2000):
            changes = dict(
                glm_blend_weight=float(np.clip(best_c.glm_blend_weight + rng4.normal(0, 0.01), 0.05, 0.40)),
                yard_cv=float(np.clip(best_c.yard_cv + rng4.normal(0, 0.02), 0.45, 1.20)),
                count_cv=float(np.clip(best_c.count_cv + rng4.normal(0, 0.02), 0.55, 1.30)),
                stat_mean_hi=float(np.clip(best_c.stat_mean_hi + rng4.normal(0, 0.03), 1.10, 1.90)),
                stat_mean_lo=float(np.clip(best_c.stat_mean_lo + rng4.normal(0, 0.02), 0.30, 0.60)),
                offense_stack_cap=float(np.clip(best_c.offense_stack_cap + rng4.normal(0, 0.01), 1.03, 1.28)),
                context_clamp_hi=float(np.clip(best_c.context_clamp_hi + rng4.normal(0, 0.008), 1.08, 1.30)),
                context_clamp_lo=float(np.clip(best_c.context_clamp_lo + rng4.normal(0, 0.008), 0.65, 0.92)),
                factor_strength={k: float(np.clip(v + rng4.normal(0, 0.04), 0.0, 1.5))
                                 for k, v in best_c.factor_strength.items()},
            )
            if sweep_new_knobs:
                changes.update(
                    depth_chart_damping=float(np.clip(best_c.depth_chart_damping + rng4.normal(0, 0.03), 0.0, 1.0)),
                    role_change_retention=float(np.clip(best_c.role_change_retention + rng4.normal(0, 0.03), 0.0, 1.0)),
                )
            c = phase3_c.replace(**changes)
            m = evaluate(c, cache)
            if (
                m["bias_abs"] <= gate_bias_max
                and m["rank_corr"] >= base_rank - _RANK_TOL
                and m["objective"] < best_m["objective"]
            ):
                best_m, best_c = m, c
                gate_ok = True
        if gate_ok:
            _log(_summary("phase-4 best (gate-compliant)", best_m))
        else:
            _log(
                f"\n**Phase 4 found no gate-compliant point within 2000 local "
                f"perturbations of the Phase-3 optimum. Keeping the Phase-3 "
                f"result (|bias|={phase3_m['bias_abs']:.4f}) -- "
                f"verify_fantasy_calibration.py will report the exact miss.**"
            )

    _log("\n## FINAL\n```json\n" + json.dumps(best_c.to_dict(), indent=2, sort_keys=True) + "\n```")
    _log("final metrics:\n```json\n" + json.dumps(best_m, indent=2) + "\n```")
    save_calibration(best_c, ARTIFACT)
    _log(f"\nwritten -> {ARTIFACT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--validate-approx", action="store_true")
    ap.add_argument("--validate-new-knobs", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.build_cache:
        print(build_eval_cache(2025))
    elif a.validate_approx:
        sys.exit(0 if validate_approx() <= 0.05 else 1)
    elif a.validate_new_knobs:
        sys.exit(0 if validate_new_knobs() <= 0.01 else 1)
    elif a.run:
        run()
    else:
        ap.print_help()
