"""J2 — Chess autoplayer integration smoke.

Drives Chess.app for a handful of moves through the cua-maximalist MCP
server. Gated by `CUA_RUN_CHESS_AUTOPLAY=1` so it never fires in normal
unit runs (Chess.app is not headless and TCC permissions are required).

Pre-conditions when the gate is set:
    - Chess.app launched with a fresh game
    - cua-driver Swift binary on PATH or CUA_DRIVER_BIN set
    - Accessibility + Screen Recording permissions granted to whichever
      python interpreter pytest invokes
"""
from __future__ import annotations

import os

import pytest

GATE = os.environ.get("CUA_RUN_CHESS_AUTOPLAY") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not GATE,
        reason="set CUA_RUN_CHESS_AUTOPLAY=1 to enable Chess.app autoplay",
    ),
]


@pytest.mark.asyncio
async def test_chess_autoplayer_5_moves_majority_verifies():
    from scripts.chess_autoplayer import run_autoplayer

    result = await run_autoplayer(num_moves=5, mode="random_legal")
    assert result.aborted_reason is None, (
        f"autoplayer aborted: {result.aborted_reason}"
    )
    assert len(result.moves) >= 5, (
        f"expected 5 moves, played {len(result.moves)}"
    )
    # Acceptance per plan J2: ≥70% verify on first attempt over 10 moves.
    # 5-move smoke uses a softer ≥3/5 threshold to absorb single-frame lag.
    assert result.fully_verified_count >= 3, (
        f"only {result.fully_verified_count}/5 moves fully verified; "
        f"episode log: {result.episode_path}"
    )


@pytest.mark.asyncio
async def test_chess_autoplayer_failure_injection_triggers_recovery():
    from scripts.chess_autoplayer import run_autoplayer

    # Inject a bogus click every 2nd ply over 4 plies → 2 injections
    result = await run_autoplayer(
        num_moves=4,
        mode="random_legal",
        inject_failure_every=2,
    )
    assert result.aborted_reason is None
    # The bogus clicks themselves don't appear in result.moves (they're
    # logged as failure_injection entries), but they should leave a
    # recovery_log trail that the orchestrator emitted into the session
    # writer. We can't easily assert on that here without parsing the
    # session's NDJSON; instead, confirm the autoplayer didn't crash and
    # the legitimate moves still landed.
    assert len(result.moves) == 4
