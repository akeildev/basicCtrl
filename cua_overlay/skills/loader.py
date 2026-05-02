"""Skills loader — surface per-app skill markdown to cognition prompts.

Skills are markdown files at `cua_overlay/skills/<bundle_id>/*.md`.
They're not load-bearing for the framework (no behavior depends on
their content); they're reference text that B3/B4 cognition agents
can include in their prompts when planning recovery for a known app.

Pattern borrowed from browser-harness — agents PR back what they
learn; the next run benefits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


_SKILLS_DIR = Path(__file__).parent


def list_bundles() -> list[str]:
    """Return all bundle_ids that have at least one skill file."""
    return sorted(
        p.name
        for p in _SKILLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("__") and any(p.glob("*.md"))
    )


def list_skills(bundle_id: str) -> list[str]:
    """Return skill topic names (filename stem) for a bundle, e.g. ['general', 'messaging']."""
    bundle_dir = _SKILLS_DIR / bundle_id
    if not bundle_dir.is_dir():
        return []
    return sorted(p.stem for p in bundle_dir.glob("*.md"))


def read_skill(bundle_id: str, topic: str) -> Optional[str]:
    """Return the markdown content of one skill, or None if missing."""
    path = _SKILLS_DIR / bundle_id / f"{topic}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def read_all_skills(bundle_id: str) -> Optional[str]:
    """Concatenate every skill for a bundle into a single text blob.

    Returns None when the bundle has no skills (no extra prompt context).
    Useful for a B3/B4 cognition prompt: "Here's what we know about
    com.apple.calculator: <blob>".
    """
    topics = list_skills(bundle_id)
    if not topics:
        return None
    parts = [f"# Skills for {bundle_id}\n"]
    for topic in topics:
        body = read_skill(bundle_id, topic)
        if body:
            parts.append(f"\n---\n## {topic}\n\n{body}\n")
    return "".join(parts)
