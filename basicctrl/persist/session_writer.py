"""SessionWriter — per-session ``~/.cua/sessions/<uuid>/`` directory tree.

PERSIST-02: every running session owns a dedicated directory whose layout is
fixed across all phases. Phase 1 only writes ``snapshot.json``,
``action_log.ndjson``, and (via Plan 07 Task 2) ``checkpoints/``. The other
subdirs are created empty as forward-compatibility placeholders for Phase 3
(cassettes, heals), Phase 4 (recipes), and Phase 5 (recordings).

Layout (per ARCHITECTURE.md L124-130)::

    ~/.cua/sessions/<session_id>/
    ├── snapshot.json            # last full StateGraph snapshot (atomic write)
    ├── action_log.ndjson        # structlog NDJSON, every Hoare triple
    ├── heals.ndjson             # Phase 3 heal events (Phase 1: empty)
    ├── checkpoints/             # LangGraph checkpoint shards (Postgres-mirrored)
    ├── recipes/                 # Phase 4: ghost-os recipe JSON
    ├── cassettes/               # Phase 3: Stagehand-style replay tapes
    ├── recordings/              # Phase 5: 60fps H.265
    └── profile_snapshot/        # Cached AppProfile bundles for this session

Notes
-----
* ``session_id`` is a UUID4 generated at instantiation unless one is pinned by
  the caller (Plan 09 demo + resume tests pin one for determinism).
* ``append_action_log`` writes one valid JSON line per call (NDJSON / JSONL).
  Each line is one ``ActionCanonical`` or ``HoarePost`` event — never a
  pasteboard payload (T-1-03: see ``basicctrl/log.py`` redactor).
* ``write_snapshot`` is atomic via ``snapshot_io.atomic_write_json`` —
  ``tempfile + os.replace`` so crashes never leave torn writes.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog

from basicctrl.persist.snapshot_io import atomic_write_json, read_json


class SessionWriter:
    """Per-session directory tree under ``~/.cua/sessions/<uuid>/``.

    Created at instantiation: subdirectories and the ``heals.ndjson`` /
    ``action_log.ndjson`` placeholders are all materialised so downstream
    callers (Plan 08 MCP startup, Plan 09 Calculator demo, Phase 3 healer)
    can ``open(...)`` any of them without first checking existence.
    """

    SUBDIRS: list[str] = [
        "checkpoints",
        "recipes",
        "cassettes",
        "recordings",
        "profile_snapshot",
    ]
    EMPTY_FILES: list[str] = ["heals.ndjson"]

    def __init__(
        self,
        base: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._base = base if base is not None else Path.home() / ".cua" / "sessions"
        self._dir = self._base / self._session_id
        self._dir.mkdir(parents=True, exist_ok=True)
        for sub in self.SUBDIRS:
            (self._dir / sub).mkdir(parents=True, exist_ok=True)
        for fname in self.EMPTY_FILES:
            (self._dir / fname).touch()
        # Always ensure action_log.ndjson exists so callers can open it append-mode
        self.action_log_path.touch()
        structlog.get_logger().info(
            "session.created",
            session_id=self._session_id,
            dir=str(self._dir),
        )

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def action_log_path(self) -> Path:
        return self._dir / "action_log.ndjson"

    @property
    def snapshot_path(self) -> Path:
        return self._dir / "snapshot.json"

    @property
    def heals_path(self) -> Path:
        return self._dir / "heals.ndjson"

    def append_action_log(self, event: dict[str, Any]) -> None:
        """Append one NDJSON line. Each call writes one ``json.dumps(event)\\n``.

        T-1-03 caller responsibility: do NOT pass pasteboard payload strings
        in ``event``. The structlog redactor strips them at the JSON renderer
        only — this writer is a raw NDJSON sink. Plan 05's
        ``L1Cheap._pasteboard_change_count`` returns an int; that integer is
        safe to log here, but the pasteboard string itself never should be.
        """
        with self.action_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str))
            f.write("\n")

    def write_snapshot(self, data: Any) -> None:
        """Atomic snapshot write via tmp + os.replace."""
        atomic_write_json(self.snapshot_path, data)

    def read_snapshot(self) -> Any:
        """Return the last-written snapshot dict, or ``None`` if none yet."""
        if not self.snapshot_path.exists():
            return None
        return read_json(self.snapshot_path)
