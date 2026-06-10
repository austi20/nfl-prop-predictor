# Roadmap Orchestration

Operator runbook for executing the modernization roadmap. The roadmap itself
is at `docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md`.

## When to fire each per-phase brainstorm

| Phase | Trigger | Brainstorm prompt to use |
|---|---|---|
| P2 Readiness + Loop | Now — first follow-up session | "Brainstorm P2 readiness gates + loop supervision. Spec is roadmap §2 P2. Decide: subprocess vs in-process supervision; readiness gate constants for NFL weekly cadence; quote-capture sink format (sqlite vs parquet); 4 routes contract." |
| P3 Live MD + ActiveTrader | After P2 ships and loop body runs for 1 week paper | "Brainstorm P3 live market data + ActiveTrader FSM. Spec is roadmap §2 P3. Decide: FSM state transitions + invariants; WS disconnect recovery policy; CandidateProvider interface to eval/ PropDecisions." |
| P5 Calibration + ECE | After preseason wk 2 — real quotes captured | "Brainstorm P5 calibration pipeline. Spec is roadmap §2 P5 + §5 P2. Decide: isotonic vs Platt fallback thresholds; min_samples per (position, stat); ECE binning; artifact namespacing. Walk-forward only." |
| P4 Decision Brain | After P5 calibrator validates on captured quotes | "Brainstorm P4 decision brain. Spec is roadmap §2 P4. Decide: NFL series alias map (from cache/kalshi_nfl_series.json); SelectionStore schema; LLM advisory wrapper API enforcing downgrade-only invariant; row-zero ranking logic." |
| P7 Brain + Agents | After P4 has 3 weeks of real outcomes | "Brainstorm P7 brain + agents. Spec is roadmap §2 P7. Decide: BrainStore SQLite schema; vault bridge frontmatter; signal-to-noise thresholds for safety caps tuned to observed variance." |
| P6b Router migration | Before TanStack Router migration starts | "Brainstorm P6b router migration. Spec is roadmap §2 P6. Decide: file-route layout; feature flag for rollback; parity test plan." |
| P6f React 19 bump | Before React 19 bump starts | "Brainstorm P6f React 19 bump. Spec is roadmap §2 P6. Decide: Tauri 2 compat check; Radix primitive compat; worktree-branch strategy." |

## What to skip the brainstorm for

P6a (openapi codegen), P6c (trading routes — schema locked at P2), P6d
(startup snapshot — schema locked at P5), P6e (virtual tables) are
mechanical. Plan them inline in their PRs.

## Cross-phase invariants

- **Model > GUI on resource conflict.** Track B yields. P6e + P6f drop first.
- **LLM downgrade-only.** P4 wrapper enforces; CI test asserts no upgrade path.
- **Walk-forward only.** No random k-fold on time-series data.
- **Layer B is a merge gate.** PR template references `docs/breakpoints/p<N>_evaluation.md`; `tests/test_breakpoint_doc_gate.py` enforces.
- **Track B is preemptible at any phase boundary.**

## Pre-work shipped (this plan)

- Breakpoint template + README at `docs/breakpoints/`
- Breakpoint doc CI gate (`scripts/check_breakpoint_doc.py` + test)
- PR template at `.github/PULL_REQUEST_TEMPLATE.md`
- Kalshi NFL series discovery: `scripts/discover_kalshi_nfl_series.py`
- Preseason baseline scaffold: `scripts/capture_preseason_baseline.py`
- This orchestration note
