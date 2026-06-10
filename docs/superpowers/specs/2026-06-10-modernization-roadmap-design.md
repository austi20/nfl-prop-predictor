# Modernization Roadmap (Phases 2-7) — Cross-Phase Design

**Date:** 2026-06-10
**Scope:** Cross-phase sequencing, dependencies, kill criteria, and re-brainstorm triggers for porting NBABets v2 patterns into NFLStatsPredictor. Per-phase implementation specs are out of scope here and will be authored individually at the re-brainstorm triggers named below.
**Status:** Design (awaiting user sign-off before writing-plans).
**Supersedes for forward work:** `plan.md` (Phase H).
**Sister docs:** `docs/modernization_plan.md` (gap analysis), `docs/handoff_modernization.md` (per-phase porting hints), `memory/nba_v2_reference.md` (file-level port map), `VERSIONS.md` v0.9-m1 (Phases 0-1 shipped).

---

## 0. Premises

- **Calendar:** today is 2026-06-10. NFL preseason ~ Aug 2026, ~10 weeks out. Project memory says the model layer is FROZEN until then. The roadmap treats preseason as the activation gate; pre-preseason time is for building scaffolding that activates against real quotes when they arrive.
- **Decomposition stance:** Phases 2-7 are six independent subsystems. Each will get its own spec → plan → implement cycle. This document is the roadmap that sequences them and names the triggers for those per-phase specs.
- **Source of truth for ports:** `E:\Projects\NBABets v2`. NBA v2's `app/trading/` is ~90% sport-agnostic; NFL-specific work is series mapping, prop-stat aliases, and weekly-cadence constants.
- **Already shipped (v0.9-m1, do not redo):** ruff/mypy config, sqlalchemy dep, `api/db/`, `SqlPortfolioLedger`, `SqlKillSwitch`, ExecutionService kill-switch gating, kill-switch routes, settings flags, 9 new tests.

---

## 1. Two-track dependency graph

Two work streams run in parallel from now until preseason, then converge for live activation.

```
                                           [PRESEASON GATE ~Aug 2026]
                                                      |
TRACK A (Backend) — model/trading priority            |
─────────────────                                     |
P2  Readiness + Loop ──┐                              |
                       ├─► P3  Live MD + ActiveTrader │
                       │   (paper-only, no live mode) │
                       │                              │
                       │   [QUOTE CAPTURE JOB lives in P2 loop body]
                       │                              ▼
                       │                          P5  Calibration + ECE
                       │                              │
                       │                              ▼
                       │                          P4  Decision Brain
                       │                              │
                       │                              ▼
                       │                          P7  Brain + Agents
                       │
TRACK B (Desktop) — preemptible                │
─────────────────                              │
P6a OpenAPI client gen                         │
P6b TanStack Router                            │
P6c Trading routes ◄───────────────────────────┘   (consumes P2 routes contract)
P6d Startup snapshot ◄──────────────── (consumes P5 startup endpoint)
P6e Virtual tables
P6f React 19 bump (last)
```

**Cross-track sync points:**
- **Sync 1 — P2 routes contract:** when P2 ships `/trading/readiness`, `/trading/loop/*`, Track B unblocks the Trading panel. Lock the OpenAPI schema before P6c starts so the generated client does not churn.
- **Sync 2 — P5 startup snapshot endpoint:** Track A adds `/api/startup/snapshot`; Track B's `useStartupSnapshot` hook does not ship until it exists. Order P5 before P6d.
- **Sync 3 — Preseason gate:** all Track A activation work (P5 calibration fit, P4 series-alias discovery, P7 brain) requires real Kalshi NFL quotes flowing. Calendar-blocked, not effort-blocked.

**Track B is preemptible at any phase boundary.** If Track A slips, the next-to-start Track B phase yields. P6e (virtual tables) and P6f (React 19) are the first to drop from pre-preseason scope if backend pressure rises.

---

## 2. Per-phase capsules

Each phase has: goal, prerequisites, deliverables, kill criteria, re-brainstorm trigger. Per Section 5 P3, every phase's deliverables include a `docs/breakpoints/p<N>_evaluation.md` artifact.

### P2 — Readiness + loop supervision (Track A, start now)
- **Goal:** persistent, supervised trading loop with preflight gate + watchdog + DB kill-switch check per tick. Loop body = quote-capture + mark-to-market.
- **Prereq:** P1 shipped (SQL ledger + kill switch). Done.
- **Deliverables:** `api/trading/readiness.py` (7 gates, NFL-cadence constants), `live_limits.py`, `loop_controller.py`, 4 routes (`/trading/readiness`, `/trading/loop/{status,start,stop}`), quote-capture sink (SQLite or parquet under `cache/`), `docs/breakpoints/p2_evaluation.md`.
- **Kill criteria:** if subprocess supervision proves flaky on Windows → fall back to in-process asyncio task; if Kalshi NFL series cannot be discovered before preseason → quote capture stays mocked, P5 slips.
- **Re-brainstorm trigger:** before starting. Readiness gate constants need NFL-cadence tuning (weekly vs nightly); subprocess vs in-process is a real choice with platform implications.

### P3 — Live market data + ActiveTrader (Track A, after P2)
- **Goal:** WS-driven MarketBook + PortfolioManager FSM + ActiveTrader entry gates, rehearsed on `RealisticPaperAdapter` only.
- **Prereq:** P2 loop body running; existing `kalshi/ws.py` wired in.
- **Deliverables:** `ws_consumer`, `ws_disconnect_poller`, `market_book`, `snapshot_service`, `portfolio_manager` (FSM), `active_trader`, `allocation`, `docs/breakpoints/p3_evaluation.md`.
- **Kill criteria:** FSM bugs that leak positions in paper → stop, redesign; WS reconnect storms → throttle, do not escalate to live.
- **Re-brainstorm trigger:** before starting. FSM transitions and disconnect recovery semantics need their own design pass — this is the highest-risk port.

### P5 — Model infra: calibration + ECE (Track A, preseason-gated)
- **Goal:** real-quote-fitted `ProbabilityCalibrator` with collapse guards + sample-size bounding; ECE tracking; namespaced artifact registry.
- **Prereq:** real Kalshi NFL prop quotes captured by P2 loop for at least 2 preseason weeks.
- **Deliverables:** `eval/calibration.py` + `calibration_ece.py`; `models/artifacts.py`; `feature_cache.py`; `data_sufficiency.py`; flip `use_calibration=True` after fit validates; walk-forward only (no random splits); `docs/breakpoints/p5_evaluation.md`.
- **Kill criteria:** captured quote volume insufficient by preseason week 3 → defer calibration to regular season; mean ECE worse than uncalibrated baseline on holdout → revert.
- **Re-brainstorm trigger:** after P2 quote capture has 2 weeks of real data. Design the calibration fit pipeline against actual sample sizes, not assumed ones.

### P4 — Decision brain (Track A, after P5)
- **Goal:** deterministic market/line/side selection + price gates + row-zero ranking; local LLM advisory-only, **downgrade-only**.
- **Prereq:** P5 calibrator validated; NFL Kalshi series aliases discovered (KX-NFL-* equivalents to KXNBAPTS etc.); `SelectionStore` schema.
- **Deliverables:** ported `decision_brain.py` pattern, `selections.py`, `live_pack_builder.py`, NFL vault section under `Kalshi NFL Decision Brain/`, LLM advisory wrapper enforcing downgrade-only invariant, `docs/breakpoints/p4_evaluation.md`.
- **Kill criteria:** if NFL series mapping is unstable across preseason → freeze on a subset, ship narrow; if LLM tries to upgrade selections → hard fail tests, do not ship.
- **Re-brainstorm trigger:** before starting. ~2k lines and the LLM safety invariant is *the* safety property; needs its own design + adversarial review.

### P7 — Brain + agents (Track A, last)
- **Goal:** persistent learning (BrainStore + vault bridge) with safety caps; accuracy_examiner / data_quality / prediction_validator agents.
- **Prereq:** P4 selections accumulating outcomes for at least 3 weeks; baseline performance measured.
- **Deliverables:** `BrainStore` SQLite, vault bridge to `Kalshi NFL Decision Brain/`, three agents, outcome collector, `docs/breakpoints/p7_evaluation.md`.
- **Kill criteria:** baseline (no-brain) outperforms brain-adjusted for 2 consecutive weeks → auto-revert per safety caps; if safety caps fail in test → do not ship.
- **Re-brainstorm trigger:** after P4 has 3 weeks of real outcomes. Design the learning loop against the *actual* signal-to-noise ratio observed, not the NBA v2 assumption.

### P6 — Desktop modernization (Track B, parallel-when-cheap, React 19 last)
- **Goal:** generated typed API client, file-route layout, virtualized boards, fast first paint, trading control panel.
- **Prereq:** P2 OpenAPI route contract locked (for P6c); P5 startup endpoint shipped (for P6d).
- **Deliverables (in order):** P6a openapi-typescript codegen + script; P6b TanStack Router migration; P6c `/trading` route group (loop status, readiness, kill switch); P6d `useStartupSnapshot`; P6e TanStack Virtual on slate/board tables; P6f React 18→19 bump; dep prune (audit imports first); `docs/breakpoints/p6_evaluation.md`.
- **Kill criteria:** TanStack Router migration breaks more than 2 routes → revert, do it as a separate spec; React 19 incompat with Tauri 2 → hold at 18.
- **Re-brainstorm trigger:** before P6b (router migration) and P6f (React 19 bump). Both are non-trivial migrations that warrant their own design pass.

---

## 3. Preseason activation gate

The cutover checklist when real NFL prop quotes start flowing (~Aug 2026). Single highest-leverage moment in the roadmap.

**Pre-gate (preseason week 0-1):**
1. P2 quote-capture job running ≥ 72 hours without WS disconnect storm; capture rate matches expected market polling cadence.
2. Kalshi NFL series aliases discovered and pinned. No hardcoded NBA aliases left in ported `decision_brain.py`.
3. P3 ActiveTrader FSM has run a full preseason week against `RealisticPaperAdapter` with zero leaked positions and zero stuck states.
4. P6c trading routes visible in desktop UI; kill switch trip/reset round-trips work.
5. Baseline metrics frozen: current uncalibrated GLM Brier + log-loss per stat, captured to `docs/preseason_baseline_2026.md`.

**Gate decisions (week 2-3):**
- Calibration fit: P5 calibrator fit on captured quotes; ECE must beat uncalibrated baseline on holdout — otherwise revert `use_calibration=False`.
- Decision brain dry-run: P4 generates selections against captured quotes for 1 week, **observe-only**. No paper trades. Human reviews vault notes.
- LLM advisory check: 100 selections fed through Qwen advisory layer; zero upgrades. If any upgrade slips through, ship-blocker.

**Go-live (week 4 / regular season week 1):**
- Flip `use_calibration=True`.
- P4 selections shift from `selected_observe_only` to `selected_live` for the **narrowest** slice that passed the gate.
- P7 brain remains dormant (needs at least 3 weeks of outcomes before activation).

**Rollback triggers (any time):**
- Kill switch tripped twice in 24h → loop stops, post-mortem before restart.
- Realized P&L worse than `RealisticPaperAdapter` shadow run for 2 consecutive weeks → revert to paper.
- Single ECE spike > 2× preseason value → recalibrate or revert.

---

## 4. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| **R1** | Kalshi NFL series do not exist or differ structurally from NBA series | Med | High | Discover tickers via Kalshi API in P2 before any P4 work; if missing at preseason, narrow scope to whichever stats *do* have series |
| **R2** | Quote-capture volume insufficient by preseason week 3 | Med | High | P2 captures from preseason week 0; if thin, fit calibration on combined preseason + regular wk1 and delay go-live one week |
| **R3** | WS disconnect storms on Kalshi NFL feed (weekly cadence is untested) | Med | Med | `ws_disconnect_poller` + exponential backoff; quote-capture has REST fallback path; kill switch trips on N disconnects/hour |
| **R4** | Subprocess loop supervision flaky on Windows | Low | Med | P2 kill criterion already covers fallback to in-process asyncio task; design choice deferred to P2 spec |
| **R5** | LLM advisory layer upgrades a selection (safety invariant violation) | Low | **Critical** | Hard-coded enum check in P4 wrapper; property-based test asserts no upgrade path; CI gate blocks PR if test fails |
| **R6** | TanStack Router migration breaks routes mid-flight (Track B) | Med | Med | P6b ships behind a feature flag; old routes stay until parity verified; rollback = revert one commit |
| **R7** | React 19 incompat with Tauri 2 / Radix primitives | Low | Med | P6f is last; do it in a worktree branch; revert on any breakage |
| **R8** | Track A/Track B contract drift (OpenAPI changes after P6c starts) | Med | Low | Lock P2 route contract before P6c starts; OpenAPI client regenerates on every backend PR; CI diff-check on `openapi.json` |
| **R9** | Brain (P7) auto-revert triggers too often → no learning | Low | Low | Tune sample-size minimums against real outcome variance, not NBA v2 assumption; P7 re-brainstorm trigger covers this |
| **R10** | Calendar slip: preseason arrives before P2/P3/P6 land | Med | High | Track A model/trading priority absolute; **Track B is preemptible at any phase boundary**; P6e and P6f drop first |
| **R11** | Layer B breakpoint evaluation skipped under time pressure | Med | High | Breakpoint doc is a merge gate, not optional; PR template requires `docs/breakpoints/p<N>_evaluation.md` populated before review |

**Top-3 to actively manage week-to-week:** R1 (series discovery), R2 (quote volume), R5 (LLM invariant). R5 is non-negotiable — safety property of the live system.

---

## 5. Cross-cutting principles

These override defaults wherever they conflict with earlier sections.

### P1. Model priority over GUI
Track A (backend, model, trading) outranks Track B (desktop) on every resource conflict. If a Track A item slips, the next-to-start Track B phase yields. Track B is parallel-when-cheap, not parallel-at-cost. P6e (virtual tables) and P6f (React 19) are the first to drop from pre-preseason scope.

### P2. Correctness via historically proven techniques
- **No novel modeling methods.** Defaults stay on techniques with established empirical track records:
  - Classical GLMs (already shipped — Phase H locked these in).
  - Isotonic regression for calibration with collapse guards and minimum-sample bounds. Platt scaling as fallback.
  - ECE as the primary calibration metric; Brier and log-loss as orthogonal checks.
  - Bootstrap confidence intervals where reliability matters more than speed.
- **No GBM/boosting/deep models** in P5, even though NBA v2 uses them. Modernization plan §3 already says do not copy NBA's GBM stack — reaffirmed.
- **No bespoke uncertainty quantification.** Residual-based stds (shipped in v0.8c-h2.5) and quantile distributions stay. Nothing exotic added.
- **Walk-forward only.** No random k-fold on time-series data. P5 calibration fit uses preseason-only data; out-of-sample test on regular-season wk1.
- **Prefer the simpler estimator with sample-size guards over the fancier estimator without them.** A calibrator that refuses to fit on n<50 beats one that always returns something.

### P3. Adversarial evaluation, not just tests
Every phase ships with two test layers.

**Layer A — correctness tests** (table-stakes; happy path plus standard branches): unit, integration, FSM transition coverage. 80%+ line coverage as today.

**Layer B — breakpoint evaluation** (new requirement; documented in `docs/breakpoints/p<N>_evaluation.md`):
- **Boundary probes:** behavior at exactly 0, 1, `max-1`, `max`, `max+1` for every cap, threshold, and gate. E.g. open notional `==` cap (already known: uses `>=`, not `>`), readiness staleness at exactly the window edge, calibration at exactly `min_samples`.
- **Outlier injection:** quote with 99th-percentile spread; market with stuck `last_price`; player with one historical game; stat with zero variance in the training slice. Document expected vs actual.
- **Exception paths:** WS drops mid-frame; SQLite locked; Kalshi 429; ledger and kill-switch DB out of sync; LLM returns malformed JSON; clock skew between local and Kalshi.
- **Hypothetical failure modes:** all 7 readiness gates pass but the market is wrong; calibration fit on 90% over-bias data; LLM advisory layer's downgrade is itself wrong.
- **Per-phase deliverable:** breakpoint doc enumerating probes, expected behavior, and observed behavior with evidence (logs, screenshots, db dumps).

Layer B catches silent failures Layer A green-lights. Phase H demonstrated this — k=2 was found by *evaluating* across a grid, not by *passing tests* on k=8.

---

## 6. Re-brainstorm trigger summary

| Phase | When to author per-phase spec |
|---|---|
| P2 | **Now** (next session). Constants tuning + supervision model both need design decisions. |
| P3 | After P2 ships. FSM and WS disconnect recovery need their own design pass. |
| P5 | After P2 has 2 weeks of real preseason quotes. Design against actual sample sizes. |
| P4 | After P5 validates. ~2k lines + safety invariant; needs adversarial review in the spec. |
| P7 | After P4 has 3 weeks of real outcomes. Design against measured signal-to-noise. |
| P6b | Before TanStack Router migration. Non-trivial migration. |
| P6f | Before React 19 bump. Non-trivial migration. |

Other P6 sub-phases (P6a, P6c, P6d, P6e) are mechanical enough to plan inline in their PRs.

---

## 7. What this roadmap does *not* do

- Does not specify P2 readiness gate constants, supervision model, or quote-capture schema. → P2 spec.
- Does not specify FSM transitions, WS reconnect policy, or candidate provider shape. → P3 spec.
- Does not specify calibrator sample-size thresholds or ECE binning. → P5 spec.
- Does not specify NFL Kalshi series mapping, SelectionStore schema, or LLM advisory wrapper API. → P4 spec.
- Does not specify TanStack Router file layout or generated client path conventions. → P6b sub-spec.

These are intentional — the roadmap names the triggers; the per-phase specs do the design.
