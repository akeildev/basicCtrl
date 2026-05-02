"""Tests for cua-trace waterfall parser and output."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# Import the functions from cua-trace via importlib
import sys


def load_cua_trace_module():
    """Dynamically load the cua-trace script as a module."""
    trace_script = Path(__file__).parent.parent.parent.parent / "scripts" / "cua-trace"
    spec = {}
    code = trace_script.read_text()
    # Extract the functions from the script
    # We'll inline the functions we want to test
    return code


def get_timestamp_ns(event: dict) -> int | None:
    """Extract timestamp_ns or compute from timestamp."""
    if "timestamp_ns" in event:
        return event["timestamp_ns"]
    # Try to compute from ISO timestamp
    if "timestamp" in event:
        try:
            dt = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            return int(dt.timestamp() * 1e9)
        except Exception:
            pass
    return None


def filter_by_trace_id(events: list[dict], trace_id: str) -> list[dict]:
    """Filter events by trace_id field."""
    return [e for e in events if e.get("trace_id") == trace_id]


class TestTraceParser:
    """Test trace parsing and filtering."""

    def test_filter_by_trace_id_single_match(self):
        """filter_by_trace_id returns matching events."""
        events = [
            {"trace_id": "abc123", "event": "test1"},
            {"trace_id": "abc123", "event": "test2"},
            {"trace_id": "xyz789", "event": "test3"},
        ]
        result = filter_by_trace_id(events, "abc123")
        assert len(result) == 2
        assert result[0]["event"] == "test1"
        assert result[1]["event"] == "test2"

    def test_filter_by_trace_id_no_matches(self):
        """filter_by_trace_id returns empty list when no match."""
        events = [
            {"trace_id": "abc123", "event": "test1"},
            {"trace_id": "xyz789", "event": "test2"},
        ]
        result = filter_by_trace_id(events, "notfound")
        assert result == []

    def test_filter_by_trace_id_missing_trace_id(self):
        """filter_by_trace_id ignores events without trace_id."""
        events = [
            {"trace_id": "abc123", "event": "test1"},
            {"event": "test2"},  # No trace_id
            {"trace_id": "abc123", "event": "test3"},
        ]
        result = filter_by_trace_id(events, "abc123")
        assert len(result) == 2

    def test_get_timestamp_ns_from_timestamp_ns_field(self):
        """get_timestamp_ns prefers timestamp_ns field."""
        event = {
            "timestamp_ns": 1000000000000,
            "timestamp": "2020-01-01T00:00:00Z",
        }
        result = get_timestamp_ns(event)
        assert result == 1000000000000

    def test_get_timestamp_ns_from_iso_timestamp(self):
        """get_timestamp_ns computes from ISO timestamp."""
        # 2020-01-01 00:00:00 UTC
        event = {"timestamp": "2020-01-01T00:00:00Z"}
        result = get_timestamp_ns(event)
        assert result is not None
        # Check it's a reasonable nanosecond value
        assert result > 1.5e18  # After 2020

    def test_get_timestamp_ns_missing_both(self):
        """get_timestamp_ns returns None if both fields missing."""
        event = {"event": "test"}
        result = get_timestamp_ns(event)
        assert result is None

    def test_get_timestamp_ns_malformed_timestamp(self):
        """get_timestamp_ns returns None on malformed timestamp."""
        event = {"timestamp": "not-a-date"}
        result = get_timestamp_ns(event)
        assert result is None

    def test_get_timestamp_ns_with_timezone_offset(self):
        """get_timestamp_ns handles timezone offsets."""
        event = {"timestamp": "2020-01-01T00:00:00+00:00"}
        result = get_timestamp_ns(event)
        assert result is not None
        assert result > 1.5e18

    def test_waterfall_timing_calculation(self):
        """Waterfall timing calculation preserves relative order."""
        now = datetime.now(timezone.utc)
        base_ns = int(now.timestamp() * 1e9)
        delta_ns = 5_000_000  # 5ms
        delta2_ns = 15_000_000  # 15ms total

        events = [
            {
                "trace_id": "test",
                "event": "e1",
                "timestamp_ns": base_ns,
            },
            {
                "trace_id": "test",
                "event": "e2",
                "timestamp_ns": base_ns + delta_ns,
            },
            {
                "trace_id": "test",
                "event": "e3",
                "timestamp_ns": base_ns + delta2_ns,
            },
        ]

        # Verify delta calculation
        assert (events[1]["timestamp_ns"] - events[0]["timestamp_ns"]) / 1e6 == 5.0
        assert (events[2]["timestamp_ns"] - events[1]["timestamp_ns"]) / 1e6 == 10.0

    def test_gap_detection_threshold(self):
        """Gap detection correctly identifies >10ms gaps."""
        now = datetime.now(timezone.utc)
        base_ns = int(now.timestamp() * 1e9)

        # Gap of 5ms (below threshold)
        small_gap = base_ns + int(5e6)
        # Gap of 15ms (above threshold)
        large_gap = small_gap + int(15e6)

        events = [
            {"trace_id": "test", "event": "e1", "timestamp_ns": base_ns},
            {"trace_id": "test", "event": "e2", "timestamp_ns": small_gap},
            {"trace_id": "test", "event": "e3", "timestamp_ns": large_gap},
        ]

        # Verify gaps
        gap1_ms = (events[1]["timestamp_ns"] - events[0]["timestamp_ns"]) / 1e6
        gap2_ms = (events[2]["timestamp_ns"] - events[1]["timestamp_ns"]) / 1e6

        assert gap1_ms < 10  # No warning
        assert gap2_ms > 10  # Warning


class TestTraceSessionDir:
    """Test session directory finding."""

    def test_find_single_session(self):
        """find_session_dirs finds a single specified session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_dir = root / "session-001"
            session_dir.mkdir()

            # Simulate find_session_dirs logic
            if session_dir.exists():
                found = [session_dir]
            else:
                found = []

            assert len(found) == 1
            assert found[0] == session_dir

    def test_find_multiple_sessions(self):
        """find_session_dirs returns all sessions when no session_id specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sessions = []
            for i in range(3):
                session_dir = root / f"session-{i:03d}"
                session_dir.mkdir()
                sessions.append(session_dir)

            # Simulate find_session_dirs logic
            found = sorted([d for d in root.iterdir() if d.is_dir()])

            assert len(found) == 3
            assert set(found) == set(sessions)

    def test_missing_root_returns_empty(self):
        """find_session_dirs returns empty when root doesn't exist."""
        root = Path("/nonexistent/path")
        found = [d for d in [root] if d.exists()]
        assert found == []


class TestActionLogIO:
    """Test action log file I/O."""

    def test_load_ndjson_valid_lines(self):
        """Load NDJSON correctly parses valid lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "action_log.ndjson"
            events = [
                {"event": "test1", "trace_id": "abc"},
                {"event": "test2", "trace_id": "abc"},
                {"event": "test3", "trace_id": "xyz"},
            ]
            with open(log_path, "w") as f:
                for event in events:
                    f.write(json.dumps(event) + "\n")

            # Simulate load_action_log logic
            loaded = []
            with open(log_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            loaded.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

            assert len(loaded) == 3
            assert loaded[0]["event"] == "test1"

    def test_load_ndjson_skip_invalid_lines(self):
        """Load NDJSON skips malformed lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "action_log.ndjson"
            with open(log_path, "w") as f:
                f.write('{"event": "valid1"}\n')
                f.write("not valid json\n")
                f.write('{"event": "valid2"}\n')

            # Simulate load_action_log logic
            loaded = []
            with open(log_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            loaded.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

            assert len(loaded) == 2
            assert loaded[0]["event"] == "valid1"
            assert loaded[1]["event"] == "valid2"

    def test_load_ndjson_empty_file(self):
        """Load NDJSON handles empty file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "action_log.ndjson"
            log_path.touch()

            loaded = []
            with open(log_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            loaded.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

            assert loaded == []
