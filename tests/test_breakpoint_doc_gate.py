from __future__ import annotations

import os
import subprocess

import pytest
from scripts.check_breakpoint_doc import check


def _changed_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "master...HEAD"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


GATED_PREFIXES = ("api/trading/", "eval/", "models/")


def _is_gated(paths: list[str]) -> bool:
    return any(p.startswith(GATED_PREFIXES) for p in paths)


def test_check_pure_function_no_gated_files() -> None:
    ok, msg = check(changed=["docs/foo.md"], pr_body="", diff_paths=[])
    assert ok, msg


def test_check_pure_function_gated_file_without_breakpoint_doc() -> None:
    ok, msg = check(
        changed=["api/trading/readiness.py"],
        pr_body="No breakpoint reference here.",
        diff_paths=["api/trading/readiness.py"],
    )
    assert not ok
    assert "p<N>_evaluation.md" in msg or "breakpoints" in msg


def test_check_pure_function_gated_file_with_breakpoint_doc_in_diff() -> None:
    ok, msg = check(
        changed=["api/trading/readiness.py", "docs/breakpoints/p2_evaluation.md"],
        pr_body="",
        diff_paths=["api/trading/readiness.py", "docs/breakpoints/p2_evaluation.md"],
    )
    assert ok, msg


def test_check_pure_function_gated_file_with_breakpoint_ref_in_pr_body() -> None:
    ok, msg = check(
        changed=["eval/calibration.py"],
        pr_body="See docs/breakpoints/p5_evaluation.md for Layer B.",
        diff_paths=["eval/calibration.py"],
    )
    assert ok, msg


@pytest.mark.skipif(
    not _is_gated(_changed_files()),
    reason="no gated files changed on this branch",
)
def test_branch_has_breakpoint_doc_when_gated_files_changed() -> None:
    changed = _changed_files()
    pr_body = os.environ.get("PR_BODY", "")
    ok, msg = check(changed=changed, pr_body=pr_body, diff_paths=changed)
    assert ok, msg
