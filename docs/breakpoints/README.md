# Breakpoint Evaluation Docs

Layer B of the two-layer testing requirement from the modernization roadmap
(`docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md` §5 P3).

## Why

Layer A (unit + integration tests) verifies the code does what we wrote.
Layer B verifies the code does *not* do what we didn't write — boundary
cases, outliers, exception paths, and silently-wrong scenarios.

## What

Each roadmap phase (P2, P3, P4, P5, P6, P7) produces one
`p<N>_evaluation.md` here, copied from `_template.md` and filled in.

## When

The breakpoint doc is a **merge gate**, enforced by
`tests/test_breakpoint_doc_gate.py`. A PR that touches `api/trading/`,
`eval/`, or `models/` must reference the matching phase's evaluation doc
in the PR description or include it in the diff.

## How to fill it

1. Copy `_template.md` to `p<N>_evaluation.md`.
2. Replace `<N>`, `<name>`, dates, and spec/plan paths.
3. Fill the tables with rows for every cap, gate, outlier, and exception
   path your phase introduces. Reference evidence — log lines, screenshots,
   DB dumps — not prose.
4. Check the sign-off boxes when each section is complete.
