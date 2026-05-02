"""End-to-end: drive TextEdit through T3 (AppleScript) + C4 (AppleScript fire).

Proves the AppleScript medium works end-to-end:
  - T3AppleScriptTranslator builds a `tell application "TextEdit" to ...` block
  - C4AppleScriptChannel runs it via py-applescript on a dedicated thread pool
  - We then re-read TextEdit's body via AX and assert our text is there

Skipped by default unless `CUA_RUN_E2E_TEXTEDIT=1`.

**OPERATOR GESTURE REQUIRED (one-time, per Python interpreter):**
On first run, macOS prompts "Allow <Python> to control TextEdit?" — click Allow
in System Settings → Privacy & Security → Automation. Without this grant the
osascript hangs and the test fails on timeout. This is a TCC (Transparency,
Consent, Control) per-binary requirement, not a framework bug.

If you've already granted Accessibility to your Python interpreter for the
Calculator tests, you still need a SEPARATE Automation grant for TextEdit
(per-target-app, per-source-binary).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from pathlib import Path

import anyio
import pytest

from cua_overlay.actions.channels.c4_applescript import C4AppleScriptChannel
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.persist.session_writer import SessionWriter
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TargetSpec
from cua_overlay.translators.t3_applescript import T3AppleScriptTranslator


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_TEXTEDIT") != "1",
        reason="TextEdit T3+C4 e2e; needs TCC Automation grant + "
               "set CUA_RUN_E2E_TEXTEDIT=1 to run",
    ),
]


def _read_textedit_body(pid: int) -> str | None:
    """Walk TextEdit's AX tree and return the AXValue of the document body
    (an AXTextArea inside the front window)."""
    from ApplicationServices import (  # type: ignore[import-not-found]
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
    )
    app = AXUIElementCreateApplication(pid)
    queue: list[tuple[object, int]] = [(app, 0)]
    seen = 0
    while queue and seen < 200:
        elem, depth = queue.pop(0)
        seen += 1
        _, role = AXUIElementCopyAttributeValue(elem, "AXRole", None)
        _, value = AXUIElementCopyAttributeValue(elem, "AXValue", None)
        if role == "AXTextArea" and value is not None:
            return str(value)
        if depth >= 8:
            continue
        _, children = AXUIElementCopyAttributeValue(elem, "AXChildren", None)
        if children:
            for c in list(children)[:50]:
                queue.append((c, depth + 1))
    return None


@pytest.fixture
def textedit_pid() -> int:
    """Launch TextEdit + open a new document. Returns its pid.

    First call may stall briefly if macOS hasn't already granted Automation
    permission for this Python binary. The fixture skips (not fails) on
    AppleScript timeout — see the module docstring for the operator gesture.
    """
    subprocess.run(["pkill", "-9", "-x", "TextEdit"], check=False)
    time.sleep(1.5)
    subprocess.run(["open", "-a", "TextEdit"], check=True)
    time.sleep(2.0)
    ps = subprocess.run(["pgrep", "-x", "TextEdit"], capture_output=True, text=True)
    pid = int(ps.stdout.strip())

    # Make a new document via AppleScript. If Automation permission is denied
    # this hangs — wrap in timeout.
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "TextEdit" to make new document'],
            check=False, timeout=5.0,
        )
    except subprocess.TimeoutExpired:
        pytest.skip(
            "AppleScript to TextEdit timed out — likely missing TCC Automation "
            "grant. Open System Settings → Privacy & Security → Automation, "
            "and approve your Python interpreter for TextEdit."
        )
    time.sleep(1.0)
    return pid


@pytest.mark.asyncio
async def test_t3_c4_writes_text_to_textedit(
    textedit_pid: int, tmp_path: Path
) -> None:
    """Drive TextEdit via T3+C4 to set its document body, verify via AX."""
    pid = textedit_pid
    text = "hello from cua-maximalist"

    sw = SessionWriter(base=tmp_path)
    store = IdempotencyTokenStore(sw)
    t3 = T3AppleScriptTranslator()
    chan = C4AppleScriptChannel(translator=t3)

    target_spec = TargetSpec(
        as_verb=f'set text of front document to "{text}"',
        label="document_body",
    )
    target = await t3.resolve("com.apple.TextEdit", pid, target_spec)
    assert target is not None, "T3 should be able to address TextEdit"
    assert target.as_target_spec, "T3 must populate as_target_spec"

    action = ActionCanonical(
        id=uuid.uuid4().hex,
        step_idx=0,
        kind="MUTATE",
        target_key="textedit_body",
        action_type="set_value",
        payload={"text": text},
        timestamp_ns=time.monotonic_ns(),
        session_id="textedit-e2e",
    )
    outcome = await chan.fire(action, target, store, anyio.Event())
    assert outcome.status == "fired", (
        f"C4 should fire; got status={outcome.status} err={outcome.error}"
    )

    await asyncio.sleep(0.5)

    body = _read_textedit_body(pid)
    assert body is not None, "could not read TextEdit document body via AX"
    assert text in body, (
        f"expected our text in document body. Wanted {text!r} in {body!r}"
    )
