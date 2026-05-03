"""Atomic JSON read/write helpers for session-scoped persistence.

Used for ``snapshot.json`` and any other crash-resilient single-file write.
The pattern is the standard ``tempfile + os.replace`` dance:
``os.replace`` is atomic on the same filesystem, so readers either see the
previous good file or the new good file — never a half-written one.

Re-exposed at ``basicctrl.persist`` so Plan 02 (``app_profile.cache``),
Plan 08 (MCP startup snapshot), and Plan 09 (Calculator demo final snapshot)
all share the same primitive.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any) -> None:
    """Write ``data`` as JSON to ``path`` atomically (tmp + os.replace).

    The parent directory is created if missing (defensive — a fresh session
    may not have its tree on disk yet on the first write).

    The temp shard is suffixed with ``.tmp`` so a crashed prior run leaves
    a recognisable artefact that the next write cleanly replaces.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    """Read a JSON file produced by ``atomic_write_json``."""
    return json.loads(path.read_text())
