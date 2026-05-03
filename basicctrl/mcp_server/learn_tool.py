"""mcp__basicCtrl__learn — record a lesson into a skill file + commit.

The framework's existing learning loop (`register_task_complete` →
FAISS recipe + auto-write step list) only captures STEP SEQUENCES.
It does NOT capture qualitative lessons:
  - "X website's combobox is styled as text input — needs click-to-pick"
  - "Y app's title lags by ~2s after bot moves — verify via list_windows"
  - "Z platform requires SMS sign-in upfront, can't intercept code"

Those are the things that actually compound across sessions.

This tool is the explicit chokepoint for those qualitative lessons.
Every time an agent learns something non-obvious, call this with:
  - target: relative path under `basicctrl/skills/` OR a single keyword
            ("generic", "ghostty", "chess", etc.) that maps to a known
            file
  - title: short title (becomes the ### header)
  - body:  multi-line markdown body. Include WHY + HOW TO APPLY.
  - commit: bool (default True) — auto-commit the diff with a
            descriptive message so it persists across /clear and
            survives session crashes

Returns:
  {ok, file_path, lines_added, commit_hash | None, reason?}

Storage convention:
  basicctrl/skills/<bundle_id_or_keyword>/<topic>.md
  └── ## Lessons learned (auto-recorded)
      └── ### <title> — YYYY-MM-DD
          <body>

If the file or section doesn't exist, the tool creates it with the
right header/scaffolding. Idempotent: identical title+body within
the file is detected and skipped (no duplicate appends, no commit).
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Optional

import structlog
from mcp.server.fastmcp import FastMCP


_log = structlog.get_logger()


# Map shortcut keywords → known skill files. Agent can pass either
# a relative path OR a keyword.
SHORTCUTS = {
    "generic": "_generic/web-form-fill.md",
    "forms": "_generic/web-form-fill.md",
    "web-form-fill": "_generic/web-form-fill.md",
    "ghostty": "com.mitchellh.ghostty/claude-code-tabs.md",
    "chess": "com.apple.Chess/autoplay-with-stockfish.md",
    "calendar": "com.apple.iCal/quickadd.md",
    "slack": "com.tinyspeck.slackmacgap/messaging.md",
    "cursor": "com.todesktop.230313mzl4w4u92/cursor-cdp.md",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _resolve_target(target: str) -> Path:
    """Map keyword OR relative path → absolute file path under
    basicctrl/skills/."""
    skills_root = _repo_root() / "basicctrl" / "skills"
    if target in SHORTCUTS:
        return skills_root / SHORTCUTS[target]
    # Treat as relative path
    return skills_root / target


def _ensure_lessons_section(text: str) -> str:
    """If the file lacks the ## Lessons section, append the header."""
    if "## Lessons learned (auto-recorded)" in text:
        return text
    if not text.endswith("\n"):
        text += "\n"
    return (
        text
        + "\n## Lessons learned (auto-recorded)\n\n"
        + "> Entries below are auto-appended by `mcp__basicCtrl__learn` "
        + "after sessions where the agent discovered something non-obvious. "
        + "Read this section before retrying a flow that previously "
        + "produced surprises.\n"
    )


def _format_block(title: str, body: str) -> str:
    today = date.today().isoformat()
    return f"\n### {title} — {today}\n\n{body.rstrip()}\n"


def _commit_change(path: Path, summary: str) -> Optional[str]:
    """git add + commit. Returns commit SHA or None on failure."""
    repo = _repo_root()
    try:
        subprocess.run(["git", "-C", str(repo), "add", str(path)],
                       check=True, capture_output=True, timeout=15)
        msg = (
            f"skill(learn): {summary}\n\n"
            f"Auto-recorded by mcp__basicCtrl__learn after a session "
            f"discovered a non-obvious pattern. See the file's "
            f"'Lessons learned' section.\n\n"
            f"Co-Authored-By: Claude Opus 4.7 (1M context) "
            f"<noreply@anthropic.com>\n"
        )
        result = subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", msg],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return None
        # Get SHA
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return sha
    except Exception:
        return None


def register_learn_tool(proxy: FastMCP) -> None:
    """Register mcp__basicCtrl__learn on the proxy."""

    @proxy.tool(
        name="learn",
        description=(
            "Record a non-obvious LESSON into the right skill file + "
            "auto-commit so it survives /clear and persists across "
            "future sessions.\n\n"
            "WHEN TO CALL\n"
            "Call this BEFORE replying to the user whenever a session "
            "discovered any of:\n"
            "- A new app's AX label format / DOM pattern / API quirk\n"
            "- A trap + workaround (focus race, title lag, validation "
            "  surprise)\n"
            "- A faster path than the obvious one\n"
            "- An external tool needed (brew install X, pip install Y)\n"
            "- Bot/app deviation pattern + recovery\n"
            "- A web-form combobox/select that needs special handling\n"
            "- Anything you'd want a future agent to know upfront\n\n"
            "Telling the user a lesson without filing it = next session "
            "re-learns from scratch. ALWAYS file before reply.\n\n"
            "ARGS\n"
            "  target: keyword (e.g. 'forms', 'chess', 'ghostty', 'slack') "
            "          OR relative path under basicctrl/skills/ "
            "          (e.g. 'com.example.app/topic.md')\n"
            "  title:  short title for the ### header\n"
            "  body:   multi-line markdown. Structure as:\n"
            "          - what was surprising\n"
            "          - WHY it happens (mechanism)\n"
            "          - HOW TO APPLY next time (concrete steps)\n"
            "          - file:line refs when applicable\n"
            "  commit: bool (default True) — git commit + push the diff\n\n"
            "Idempotent: identical title+body in file is detected, "
            "no duplicate append.\n\n"
            "AVAILABLE SHORTCUTS\n"
            "  generic | forms | web-form-fill → _generic/web-form-fill.md\n"
            "  ghostty                          → com.mitchellh.ghostty/...\n"
            "  chess                            → com.apple.Chess/...\n"
            "  calendar                         → com.apple.iCal/...\n"
            "  slack                            → com.tinyspeck.slackmacgap/...\n"
            "  cursor                           → com.todesktop.../...\n"
            "Anything else: pass relative path."
        ),
    )
    async def learn(
        target: str,
        title: str,
        body: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        path = _resolve_target(target)

        if not path.parent.exists():
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

        existing = ""
        if path.exists():
            existing = await asyncio.to_thread(path.read_text, encoding="utf-8")

        # Idempotency: skip if exact title+body present
        new_block = _format_block(title, body)
        # Drop the date stamp from comparison so re-runs don't dup
        check_block = re.sub(r" — \d{4}-\d{2}-\d{2}\n", "\n", new_block)
        check_existing = re.sub(r" — \d{4}-\d{2}-\d{2}\n", "\n", existing)
        if check_block.strip() in check_existing:
            return {
                "ok": True,
                "file_path": str(path),
                "lines_added": 0,
                "reason": "already_recorded",
            }

        new_text = _ensure_lessons_section(existing) + new_block
        await asyncio.to_thread(path.write_text, new_text, encoding="utf-8")
        lines_added = new_text.count("\n") - existing.count("\n")

        commit_sha: Optional[str] = None
        if commit:
            commit_sha = await asyncio.to_thread(
                _commit_change, path, f"{path.name}: {title}"
            )

        _log.info("learn.recorded", file=str(path), title=title,
                  lines_added=lines_added, commit=commit_sha)
        return {
            "ok": True,
            "file_path": str(path),
            "lines_added": lines_added,
            "commit_hash": commit_sha,
        }

    _log.info("learn_tool.registered", tool="learn")
