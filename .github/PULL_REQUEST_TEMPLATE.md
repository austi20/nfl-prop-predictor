## Summary

<one or two sentences — what changed and why>

## Phase

<which roadmap phase, if any — e.g. P2 readiness, P6c trading routes, or "n/a">

## Test plan

- [ ] Layer A (correctness): `uv run pytest -q` green
- [ ] ruff: `uv run ruff check api tests scripts` green
- [ ] mypy (if applicable): `uv run mypy api` green
- [ ] Manual verification (if applicable): <what you did>

## Layer B — Breakpoint evaluation

If this PR touches `api/trading/`, `eval/`, or `models/`, link the
breakpoint evaluation doc:

`docs/breakpoints/p<N>_evaluation.md`

Required by `docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md` §5 P3.
Enforced by `tests/test_breakpoint_doc_gate.py`.

## Roadmap risks affected

<R-numbers from §4 of the roadmap spec, or "none">

## Notes for reviewer

<anything non-obvious — invariants, follow-ups, deferred items>
