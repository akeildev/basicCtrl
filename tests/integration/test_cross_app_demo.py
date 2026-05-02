"""J3/J4 — Calculator → TextEdit cross-app demo.

Gated by `CUA_RUN_E2E_CROSS_APP=1`. Requires Calculator.app + TextEdit.app
+ cua-driver binary + TCC permissions.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

GATE = os.environ.get("CUA_RUN_E2E_CROSS_APP") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not GATE, reason="set CUA_RUN_E2E_CROSS_APP=1 to enable cross-app demo"
    ),
]


@pytest.mark.asyncio
async def test_calc_then_textedit_writes_math_txt():
    from scripts.cross_app_demo import OUTPUT_FILE, cleanup_artifact, run_demo

    cleanup_artifact()  # ensure no stale file
    try:
        result = await run_demo()
        assert result.aborted_reason is None, result.aborted_reason
        assert result.textedit_save_succeeded, "TextEdit save failed"
        assert result.file_verified, (
            f"~/math.txt content mismatch: got {result.file_content!r}, "
            f"expected '391'"
        )
        # Spot-check that ≥4/7 calc clicks verified — the AX labels for
        # specific keys may differ across macOS versions but a majority
        # should always land.
        verified_count = sum(1 for s in result.calc_steps if s.verified)
        assert verified_count >= 4, (
            f"only {verified_count}/7 calc clicks verified"
        )
    finally:
        cleanup_artifact()


@pytest.mark.asyncio
async def test_failure_injection_does_not_break_post_calc_textedit_flow():
    """J4: kill Calculator mid-sequence; TextEdit must still produce the
    file. Recovery branches log the heal attempt to the session writer."""
    from scripts.cross_app_demo import cleanup_artifact, run_demo

    cleanup_artifact()
    try:
        result = await run_demo(fail_after_step=3)
        assert result.aborted_reason is None
        # The TextEdit phase runs unconditionally, so the file should
        # still land regardless of Calculator's state.
        assert result.file_verified, (
            f"~/math.txt missing after failure injection; "
            f"content={result.file_content!r}"
        )
    finally:
        cleanup_artifact()
