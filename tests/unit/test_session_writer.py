"""Unit tests for ``basicctrl.persist.session_writer.SessionWriter``.

Covers PERSIST-02:
* Per-session ~/.cua/sessions/<uuid>/ tree creation at instantiation
* UUID4 session_id generation
* NDJSON action_log appends
* Atomic snapshot writes (tmp + os.replace, no torn writes on crash)
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from basicctrl.persist.session_writer import SessionWriter
from basicctrl.persist.snapshot_io import atomic_write_json, read_json


_UUID4_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
)


def test_tree_created(tmp_path: Path) -> None:
    """Constructing SessionWriter creates the full subdirectory tree.

    Asserts every subdir from the architecture-doc layout exists, plus
    heals.ndjson is present and zero bytes (Phase 3 will populate it).
    """
    writer = SessionWriter(base=tmp_path)
    assert writer.dir == tmp_path / writer.session_id
    assert writer.dir.exists() and writer.dir.is_dir()
    for sub in ("checkpoints", "recipes", "cassettes", "recordings", "profile_snapshot"):
        d = writer.dir / sub
        assert d.exists(), f"missing subdir: {sub}"
        assert d.is_dir(), f"{sub} is not a directory"
    heals = writer.dir / "heals.ndjson"
    assert heals.exists()
    assert heals.stat().st_size == 0


def test_session_id_is_uuid4(tmp_path: Path) -> None:
    """session_id matches the canonical UUID4 string format."""
    writer = SessionWriter(base=tmp_path)
    assert _UUID4_RE.match(writer.session_id), (
        f"session_id {writer.session_id!r} is not a UUID4"
    )
    # Round-trip via uuid.UUID — must parse and have version 4.
    parsed = uuid.UUID(writer.session_id)
    assert parsed.version == 4


def test_two_writers_get_distinct_ids(tmp_path: Path) -> None:
    """Two SessionWriter instances produce distinct session_ids and
    distinct directories."""
    a = SessionWriter(base=tmp_path)
    b = SessionWriter(base=tmp_path)
    assert a.session_id != b.session_id
    assert a.dir != b.dir
    assert a.dir.exists() and b.dir.exists()


def test_action_log_append(tmp_path: Path) -> None:
    """append_action_log writes one valid JSON line per call."""
    writer = SessionWriter(base=tmp_path)
    writer.append_action_log({"event": "test", "step_idx": 0})
    raw = writer.action_log_path.read_text()
    lines = [ln for ln in raw.splitlines() if ln]
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"event": "test", "step_idx": 0}


def test_action_log_appendable_in_order(tmp_path: Path) -> None:
    """Appending three events yields three JSON lines, in order."""
    writer = SessionWriter(base=tmp_path)
    for i in range(3):
        writer.append_action_log({"event": "step", "step_idx": i})
    raw = writer.action_log_path.read_text()
    lines = [ln for ln in raw.splitlines() if ln]
    assert len(lines) == 3
    parsed = [json.loads(ln) for ln in lines]
    assert [p["step_idx"] for p in parsed] == [0, 1, 2]


def test_snapshot_atomic_write(tmp_path: Path) -> None:
    """write_snapshot leaves no .tmp file behind; final file is valid JSON."""
    writer = SessionWriter(base=tmp_path)
    writer.write_snapshot({"version": 1, "state": "ok"})

    # No leftover .tmp shard
    leftovers = list(writer.dir.glob("*.tmp"))
    assert leftovers == [], f"unexpected .tmp leftovers: {leftovers}"

    # Final file parses cleanly
    parsed = json.loads(writer.snapshot_path.read_text())
    assert parsed == {"version": 1, "state": "ok"}


def test_snapshot_torn_write_recovery(tmp_path: Path) -> None:
    """A pre-existing .tmp shard from a crashed previous write is replaced cleanly.

    Simulates: a prior run wrote tmp content but crashed before os.replace fired.
    A new write_snapshot must overwrite the tmp shard and produce a valid final file.
    """
    writer = SessionWriter(base=tmp_path)
    # Plant a garbage .tmp shard simulating a crashed prior write
    bogus = writer.snapshot_path.with_suffix(writer.snapshot_path.suffix + ".tmp")
    bogus.write_text("{this is not valid json")
    # Now do a real write
    writer.write_snapshot({"version": 1, "state": "fresh"})
    parsed = json.loads(writer.snapshot_path.read_text())
    assert parsed == {"version": 1, "state": "fresh"}


def test_read_snapshot_missing_returns_none(tmp_path: Path) -> None:
    """read_snapshot returns None when no snapshot has been written yet."""
    writer = SessionWriter(base=tmp_path)
    assert writer.read_snapshot() is None


def test_read_snapshot_round_trip(tmp_path: Path) -> None:
    """Write then read returns the original dict."""
    writer = SessionWriter(base=tmp_path)
    payload = {"version": 1, "state": "round-trip", "n": 42}
    writer.write_snapshot(payload)
    assert writer.read_snapshot() == payload


def test_atomic_write_json_creates_parent(tmp_path: Path) -> None:
    """atomic_write_json mkdirs the parent directory (defensive)."""
    target = tmp_path / "deep" / "nested" / "out.json"
    atomic_write_json(target, {"k": "v"})
    assert target.exists()
    assert read_json(target) == {"k": "v"}


def test_session_writer_with_explicit_session_id(tmp_path: Path) -> None:
    """A caller can pin the session_id (used by Plan 09 demo + resume tests)."""
    pinned = "12345678-1234-4321-89ab-cdef12345678"
    writer = SessionWriter(base=tmp_path, session_id=pinned)
    assert writer.session_id == pinned
    assert writer.dir == tmp_path / pinned
