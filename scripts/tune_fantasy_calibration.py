"""Tune FantasyCalibration against the 2025 backtest cache. All four positions
are scored per-position-balanced (eval.fantasy_calibration.evaluate).

  uv run python scripts/tune_fantasy_calibration.py --build-cache
  uv run python scripts/tune_fantasy_calibration.py --validate-approx
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


def _better(cand: dict, best: dict, base_rank: float) -> bool:
    return cand["objective"] < best["objective"] and cand["rank_corr"] >= base_rank - _RANK_TOL


def run() -> None:
    cache = load_eval_cache()
    base = default_calibration()
    bias, vinf = _load_or_fit_correction()
    base = base.replace(glm_bias=bias, glm_var_inflation=vinf)
    base_m = evaluate(base, cache)
    base_rank = base_m["rank_corr"]
    _log("\n## Sweep run")
    _log(f"GLM correction (bias): {json.dumps(bias, sort_keys=True)}")
    _log(f"GLM correction (var_inflation): {json.dumps(vinf, sort_keys=True)}")
    _log(_summary("post-correction baseline", base_m))

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
        c = best_c.replace(
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
        m = evaluate(c, cache)
        if _better(m, best_m, base_rank):
            best_m, best_c = m, c
    _log(_summary("phase-3 best", best_m))

    _log("\n## FINAL\n```json\n" + json.dumps(best_c.to_dict(), indent=2, sort_keys=True) + "\n```")
    _log("final metrics:\n```json\n" + json.dumps(best_m, indent=2) + "\n```")
    save_calibration(best_c, ARTIFACT)
    _log(f"\nwritten -> {ARTIFACT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--validate-approx", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.build_cache:
        print(build_eval_cache(2025))
    elif a.validate_approx:
        sys.exit(0 if validate_approx() <= 0.05 else 1)
    elif a.run:
        run()
    else:
        ap.print_help()
