# Breakpoint Evaluation — Phase P<N>: <name>

**Phase:** P<N>
**Author:** <name>
**Date:** YYYY-MM-DD
**Spec:** `docs/superpowers/specs/YYYY-MM-DD-p<N>-<topic>-design.md`
**Plan:** `docs/superpowers/plans/YYYY-MM-DD-p<N>-<topic>.md`

This document is Layer B of the testing requirement defined in
`docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md` §5 P3.
It is a merge gate, not optional.

## 1. Boundary probes

For every cap, threshold, and gate introduced by this phase, document
behavior at exactly `0`, `1`, `max-1`, `max`, `max+1`.

| Cap / Gate | Value | Expected | Observed | Evidence |
|---|---|---|---|---|
| <name> | 0 | <expected> | <observed> | <log/screenshot ref> |
| <name> | max | <expected> | <observed> | <log/screenshot ref> |

## 2. Outlier injection

| Scenario | Input | Expected | Observed | Evidence |
|---|---|---|---|---|
| 99th-pct spread quote | <input> | <expected> | <observed> | <ref> |
| Stuck last_price | <input> | <expected> | <observed> | <ref> |
| Singleton-history player | <input> | <expected> | <observed> | <ref> |
| Zero-variance stat slice | <input> | <expected> | <observed> | <ref> |

## 3. Exception paths

| Failure mode | Trigger | Expected recovery | Observed | Evidence |
|---|---|---|---|---|
| WS drop mid-frame | <how injected> | <expected> | <observed> | <ref> |
| SQLite locked | <how injected> | <expected> | <observed> | <ref> |
| Kalshi HTTP 429 | <how injected> | <expected> | <observed> | <ref> |
| Ledger / kill-switch DB out of sync | <how injected> | <expected> | <observed> | <ref> |
| LLM malformed JSON | <how injected> | <expected> | <observed> | <ref> |
| Clock skew (local vs Kalshi) | <how injected> | <expected> | <observed> | <ref> |

## 4. Hypothetical failure modes

Free-form. Enumerate the "what if X is silently wrong" scenarios specific to
this phase. Each must have an answer for: how would we detect it; how would
we recover; is there a test or monitor in place.

## 5. Sign-off

- [ ] All boundary probes documented with evidence.
- [ ] All outlier scenarios exercised.
- [ ] All exception paths tested or explicitly waived with rationale.
- [ ] Hypothetical failure modes have detection + recovery answers.

Reviewed by: <name>
Date: YYYY-MM-DD
