"""Breakpoint doc merge gate.

Used by tests/test_breakpoint_doc_gate.py to enforce that any PR touching the
gated phase-territory directories also includes (in diff or PR body) a reference
to the matching docs/breakpoints/p<N>_evaluation.md doc.

Defined in docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md §5 P3.
"""
from __future__ import annotations

import re

GATED_PREFIXES: tuple[str, ...] = ("api/trading/", "eval/", "models/")
BREAKPOINT_DOC_PATTERN = re.compile(r"docs/breakpoints/p\d+_evaluation\.md")


def _has_gated_change(changed: list[str]) -> bool:
    return any(p.startswith(GATED_PREFIXES) for p in changed)


def _breakpoint_doc_in_diff(diff_paths: list[str]) -> bool:
    return any(BREAKPOINT_DOC_PATTERN.search(p) is not None for p in diff_paths)


def _breakpoint_doc_in_pr_body(pr_body: str) -> bool:
    return BREAKPOINT_DOC_PATTERN.search(pr_body) is not None


def check(
    *,
    changed: list[str],
    pr_body: str,
    diff_paths: list[str],
) -> tuple[bool, str]:
    """Return (ok, message).

    ok=True means the gate passes. message is empty on success, human-readable
    on failure.
    """
    if not _has_gated_change(changed):
        return True, ""
    if _breakpoint_doc_in_diff(diff_paths):
        return True, ""
    if _breakpoint_doc_in_pr_body(pr_body):
        return True, ""
    return (
        False,
        "Breakpoint gate: PR touches "
        + ", ".join(GATED_PREFIXES)
        + " but neither the diff nor the PR body references a "
        + "docs/breakpoints/p<N>_evaluation.md doc. "
        + "Add the doc (copy docs/breakpoints/_template.md) or reference an "
        + "existing one in the PR description.",
    )


if __name__ == "__main__":
    import os
    import subprocess
    import sys

    changed_out = subprocess.check_output(
        ["git", "diff", "--name-only", "master...HEAD"],
        text=True,
    )
    changed_list = [line.strip() for line in changed_out.splitlines() if line.strip()]
    pr_body_env = os.environ.get("PR_BODY", "")
    ok, msg = check(changed=changed_list, pr_body=pr_body_env, diff_paths=changed_list)
    if not ok:
        print(msg)
        sys.exit(1)
    print("breakpoint gate: OK")
