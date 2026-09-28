# Relative Boom/Bust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boom = P(points >= 1.5 x projection), bust = P(points <= 0.5 x projection), read from each player's own simulated distribution, with the point thresholds shown next to the percentages in the GUI.

**Architecture:** Only the tail readout in `eval/fantasy_points.py::project_fantasy_points` changes; the projection mean, per stat distributions, context factors and the per player sd rescale are untouched. The board row gains `boom_cutoff` / `bust_cutoff`, and the desktop renders them. A new diag script validates the definition through the real live path.

**Tech Stack:** Python 3.13, numpy, pydantic, pytest (uv). React 18 + TypeScript + vitest.

Spec: `docs/superpowers/specs/2026-09-28-relative-boom-bust-design.md`.

---

### Task 1: Relative cutoffs in the simulation readout

**Files:**
- Modify: `eval/fantasy_points.py` (constants block, `position_cutoffs`, `project_fantasy_points`)
- Modify: `api/services/fantasy_service.py:1801-1824` (two `project_fantasy_points` calls)
- Modify: `scripts/tune_fantasy_calibration.py:92,128` (approx validation)
- Test: `tests/test_fantasy_points.py`

- [ ] **Step 1: Write the failing tests.** In `tests/test_fantasy_points.py` replace the import of `position_cutoffs` with `BOOM_MULTIPLIER, BUST_MULTIPLIER, relative_cutoffs`, drop every `position=` argument, change the first test's cutoff asserts to `36.0 * 1.5` / `36.0 * 0.5`, delete `test_position_cutoffs_for_supported_positions`, and add:

```python
def test_relative_cutoffs_scale_with_the_projection():
    assert relative_cutoffs(20.0) == (20.0 * BOOM_MULTIPLIER, 20.0 * BUST_MULTIPLIER)
    assert relative_cutoffs(0.0) == (0.0, 0.0)
    assert relative_cutoffs(-1.0) == (0.0, 0.0)


def _wr() -> dict[str, StatDistribution]:
    return {
        "receptions": _dist(5.0, 2.5, "poisson"),
        "receiving_yards": _dist(65.0, 30.0, "gamma"),
        "receiving_tds": _dist(0.4, 0.6, "poisson"),
    }


def test_boom_and_bust_are_the_sample_share_past_each_cutoff():
    projection = project_fantasy_points(_wr(), seed=7, simulations=20000)
    boom_cut, bust_cut = relative_cutoffs(projection.projected_points)
    assert projection.boom_cutoff == boom_cut
    assert projection.bust_cutoff == bust_cut
    assert 0.05 < projection.boom_probability < 0.5
    assert 0.05 < projection.bust_probability < 0.5


def test_a_wider_spread_raises_both_boom_and_bust_at_the_same_projection():
    steady = project_fantasy_points(_wr(), seed=7, simulations=20000, total_sd=4.0)
    volatile = project_fantasy_points(_wr(), seed=7, simulations=20000, total_sd=9.0)
    assert steady.projected_points == volatile.projected_points
    assert volatile.boom_probability > steady.boom_probability
    assert volatile.bust_probability > steady.bust_probability


def test_half_ppr_cutoffs_follow_the_half_ppr_projection():
    half = project_fantasy_points(_wr(), scoring_mode="half_ppr", simulations=0)
    assert half.boom_cutoff == half.projected_points * BOOM_MULTIPLIER


def test_a_zero_projection_never_booms():
    projection = project_fantasy_points({}, seed=1)
    assert projection.boom_probability == 0.0
    assert projection.bust_probability == 1.0
```

- [ ] **Step 2: Run to verify they fail.** `uv run pytest tests/test_fantasy_points.py -q` → ImportError on `relative_cutoffs`.

- [ ] **Step 3: Implement.** In `eval/fantasy_points.py` replace `POSITION_CUTOFFS` and `position_cutoffs` with:

```python
# Boom = beat the projection by half again; bust = score half of it or less.
BOOM_MULTIPLIER = 1.5
BUST_MULTIPLIER = 0.5


def relative_cutoffs(projected_points: float) -> tuple[float, float]:
    if projected_points <= 0:
        return 0.0, 0.0
    return projected_points * BOOM_MULTIPLIER, projected_points * BUST_MULTIPLIER
```

Remove the `position` parameter and the `boom_cutoff, bust_cutoff = position_cutoffs(position)` line from `project_fantasy_points`. After `projected_points` and the rescale, compute:

```python
    boom_cutoff, bust_cutoff = relative_cutoffs(projected_points)
    if projected_points <= 0:
        median = p10 = p90 = projected_points
        boom, bust = 0.0, 1.0
    elif simulations <= 0:
        median = p10 = p90 = projected_points
        boom, bust = 0.0, 0.0
    else:
        median = float(np.quantile(total_samples, 0.5))
        p10 = float(np.quantile(total_samples, 0.1))
        p90 = float(np.quantile(total_samples, 0.9))
        boom = float(np.mean(total_samples >= boom_cutoff))
        bust = float(np.mean(total_samples <= bust_cutoff))
```

Drop `position=normalized_position,` from both calls in `build_fantasy_summary`. In `scripts/tune_fantasy_calibration.py` drop `position=pos,` and change the analytic line to `p_analytic, _ = _boom_bust_prob(m, sd, BOOM_MULTIPLIER * m, BUST_MULTIPLIER * m)` with `from eval.fantasy_points import BOOM_MULTIPLIER, BUST_MULTIPLIER` added to its imports.

- [ ] **Step 4: Run to verify they pass.** `uv run pytest tests/test_fantasy_points.py tests/test_fantasy_context_factors.py -q` → pass. Then `uv run ruff check eval api scripts tests --select F`.

- [ ] **Step 5: Commit.** `git commit -am "feat: boom/bust relative to the player's own projection"`

### Task 2: Cutoffs on the board row

**Files:**
- Modify: `api/schemas.py` (`FantasySlateEntry`)
- Modify: `api/services/fantasy_slate_service.py` (`_project_player` row dict)
- Test: `tests/test_fantasy_slate_service.py`

- [ ] **Step 1: Failing test.** Add `"boom_cutoff", "bust_cutoff"` to the expected key set in `test_project_player_returns_row_dict_and_swallows_failures`, add `boom_cutoff=6.0, bust_cutoff=2.0,` to the `FantasySlateEntry(...)` in `test_apply_tiers_ranks_each_list_independently`, and in `test_slate_ranks_by_projection_and_drops_thin_or_absent_history` assert `top.boom_cutoff == 20.0 and top.bust_cutoff == 8.0` (the fake summary's values).
- [ ] **Step 2:** `uv run pytest tests/test_fantasy_slate_service.py -q` → fails.
- [ ] **Step 3: Implement.** In `FantasySlateEntry` after `bust_probability: float` add:

```python
    # Points at which the week counts as a boom / bust (1.5x / 0.5x projection).
    boom_cutoff: float = 0.0
    bust_cutoff: float = 0.0
```

In `_project_player` add `"boom_cutoff": summary.boom_cutoff, "bust_cutoff": summary.bust_cutoff,` after `bust_probability`.
- [ ] **Step 4:** rerun → pass.
- [ ] **Step 5:** `git commit -am "feat: board rows carry boom/bust cutoffs"`

### Task 3: Desktop shows the thresholds

**Files:**
- Modify: `desktop/src/lib/types.ts` (`FantasySlateEntry`)
- Modify: `desktop/src/lib/format.ts` (add `boomLabel`, `bustLabel`)
- Create: `desktop/src/lib/__tests__/format.test.ts`
- Modify: `desktop/src/routes/this-week-page.tsx` (`SlateRow`)
- Modify: `desktop/src/components/player-card.tsx`

- [ ] **Step 1: Failing test** `desktop/src/lib/__tests__/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { boomLabel, bustLabel } from '../format'

describe('boom/bust labels', () => {
  it('shows the chance and the point threshold', () => {
    expect(boomLabel(0.224, 21)).toBe('22% · 21.0+')
    expect(bustLabel(0.25, 7)).toBe('25% · ≤7.0')
  })

  it('dashes a missing threshold', () => {
    expect(boomLabel(0.2, undefined)).toBe('20% · —')
  })
})
```

- [ ] **Step 2:** `npm run test --prefix desktop` → fails (no export).
- [ ] **Step 3: Implement** in `format.ts`:

```ts
/** "22% · 21.0+": chance of a boom and the points it takes. */
export function boomLabel(prob: unknown, cutoff: unknown): string {
  return `${pct(prob, 0)} · ${finite(cutoff) ? `${cutoff.toFixed(1)}+` : DASH}`
}

/** "25% · ≤7.0": chance of a bust and the points that make one. */
export function bustLabel(prob: unknown, cutoff: unknown): string {
  return `${pct(prob, 0)} · ${finite(cutoff) ? `≤${cutoff.toFixed(1)}` : DASH}`
}
```

Add `boom_cutoff: number` and `bust_cutoff: number` to `FantasySlateEntry` in `types.ts`. In `SlateRow` import the two helpers and render `boom {boomLabel(entry.boom_probability, entry.boom_cutoff)}` / `bust {bustLabel(entry.bust_probability, entry.bust_cutoff)}`; aria label ends `boom ${boomLabel(...)}, bust ${bustLabel(...)}.`. In `player-card.tsx` render `Boom {boomLabel(fantasy.boom_probability, fantasy.boom_cutoff)}` and `Bust {bustLabel(fantasy.bust_probability, fantasy.bust_cutoff)}`, and delete `fantasyPercent` if nothing else uses it.
- [ ] **Step 4:** `npx tsc -b` (from `desktop/`) and `npm run test --prefix desktop` → pass.
- [ ] **Step 5:** `git commit -am "feat(desktop): boom/bust thresholds next to the percentages"`

### Task 4: Validate through the live path

**Files:**
- Create: `scripts/diag/verify_boom_bust.py`
- Delete: `scripts/diag/verify_spread.py`
- Modify: `scripts/diag/boom_bust_drivers.py` (Brier uses relative cutoffs)

- [ ] **Step 1:** Write `verify_boom_bust.py`: builds the real board (`build_fantasy_slate`, `limit=0`) for 2025 weeks 4-17 with `use_market_anchor=False`, `use_live_forecast=False`, `prewarm_*=False`, joins each row to that week's actual `fantasy_points_ppr`, and prints per position and per projection bucket (<8, 8-14, 14+): n, mean predicted boom vs actual share `>= boom_cutoff`, same for bust, plus the pooled binned calibration error. Rows with projection < 3 are skipped (not fantasy relevant).
- [ ] **Step 2:** In `boom_bust_drivers.py` replace the `POSITION_CUTOFFS` import and lookups with `boom_cut = 1.5 * d.m`, `bust_cut = 0.5 * d.m` (import `BOOM_MULTIPLIER, BUST_MULTIPLIER`). Its output file is unchanged unless rerun.
- [ ] **Step 3:** `git rm scripts/diag/verify_spread.py`; run `uv run python scripts/diag/verify_boom_bust.py`; record the table.
- [ ] **Step 4:** If any position bucket with n >= 50 misses by more than 0.08 in boom or bust, note it as a follow up (sd refit is out of scope per spec). Commit: `git commit -am "chore: live path boom/bust validation"`.

### Task 5: Docs, full suite, ship

- [ ] `VERSIONS.md` entry `v0.9-m8` (app 0.9.4) with the validation table; memory note `project_boom_bust_pipeline.md` updated.
- [ ] `uv run pytest -q` and `npm run test --prefix desktop` green.
- [ ] Bump 0.9.3 -> 0.9.4 in pyproject, uv.lock, package.json, package-lock, tauri.conf.json, Cargo.toml, Cargo.lock; `powershell desktop/scripts/build-sidecar.ps1`; `npm run tauri build --prefix desktop`; install the MSI.
- [ ] Commit and push `feat/player-role-context`.
