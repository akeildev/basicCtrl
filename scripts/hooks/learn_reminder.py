#!/usr/bin/env python3
"""Stop hook for Claude Code — reminds the agent to file lessons.

Wires into ~/.claude/settings.json under hooks.Stop. When the agent
finishes a turn that involved framework work but DIDN'T call
mcp__basicCtrl__learn, this hook prints a short reminder to stderr.
The reminder is shown to the agent on its next turn so it self-
reflects + files the lesson before truly stopping.

Detection heuristic — fires if BOTH:
  1. Transcript shows non-trivial work (>3 tool calls in last turn,
     OR mention of trap/learned/discovered/figured-out patterns)
  2. NO mcp__basicCtrl__learn call in the recent transcript

Hook protocol (Claude Code):
  - stdin: JSON event payload with session_id, transcript_path
  - stdout: ignored
  - stderr: shown to agent on next turn
  - exit 0: pass through
  - exit 2: block stop (forces agent to handle the reminder)

This hook uses exit 0 — it informs but doesn't block. To make it
blocking, swap the final exit to 2.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Trigger phrases that suggest the agent learned something
LESSON_INDICATORS = [
    r"\btrap\b", r"\blearned\b", r"\bnon-obvious\b", r"\bdiscovered\b",
    r"\bgotcha\b", r"\bworkaround\b", r"\bfigured out\b",
    r"\bturns out\b", r"\bsubtle\b", r"\brace condition\b",
    r"\bdoesn['']?t actually\b", r"\bsurprisingly\b",
]

LEARN_CALL_PATTERNS = [
    "mcp__basicCtrl__learn",
    "basicctrl_learn",
    '"name":"learn"',  # MCP tool call shape in transcript
]


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        # Bad payload — don't block stop
        return 0

    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath")
    if not transcript_path:
        return 0

    try:
        text = Path(transcript_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    # Short transcripts: nothing learned worth saving
    if len(text) < 5000:
        return 0

    # Look at last ~100KB of transcript (recent turn activity)
    recent = text[-100_000:]

    # Did agent already call learn?
    learn_called = any(p in recent for p in LEARN_CALL_PATTERNS)
    if learn_called:
        return 0

    # Did the recent activity suggest a lesson?
    indicator_hits = sum(1 for pat in LESSON_INDICATORS
                         if re.search(pat, recent, re.IGNORECASE))
    if indicator_hits < 2:
        return 0

    # Emit reminder to agent
    sys.stderr.write(
        "🪪 basicCtrl learn-reminder:\n"
        f"  This session looked like it discovered something non-obvious "
        f"(matched {indicator_hits} lesson indicators) but did NOT call "
        f"mcp__basicCtrl__learn.\n"
        "  Before stopping, consider:\n"
        "    mcp__basicCtrl__learn(\n"
        "      target='<keyword or path>',\n"
        "      title='<short title>',\n"
        "      body='<what / why / how-to-apply>',\n"
        "    )\n"
        "  Shortcuts: forms | chess | ghostty | slack | cursor | calendar | generic.\n"
        "  Skipping = next session re-learns from scratch.\n"
    )
    # Exit 0 = pass-through (informs but doesn't block).
    # Change to 2 to BLOCK the stop until agent files a lesson.
    return 0


if __name__ == "__main__":
    sys.exit(main())
