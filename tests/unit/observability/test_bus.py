"""Tests for TraceBus — best-effort event distribution to unix socket subscribers."""
from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from basicctrl.observability.bus import TraceBus, bus_processor


@pytest.fixture
def temp_socket_path():
    """Create a temporary socket path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = Path(tmpdir) / "test.sock"
        yield socket_path
        # Cleanup
        if socket_path.exists():
            socket_path.unlink()


@pytest.fixture
def clean_bus():
    """Reset the TraceBus singleton before/after each test."""
    TraceBus.reset()
    yield
    TraceBus.reset()


class TestTraceBus:
    """Test TraceBus singleton and socket behavior."""

    def test_singleton_instance(self, clean_bus):
        """Bus.singleton() returns same instance on repeated calls."""
        bus1 = TraceBus.singleton()
        bus2 = TraceBus.singleton()
        assert bus1 is bus2

    def test_socket_init_idempotent(self, clean_bus):
        """_init_socket() is idempotent."""
        bus = TraceBus.singleton()
        sock1 = bus._server_socket
        bus._init_socket()
        sock2 = bus._server_socket
        # Same socket object (or None)
        assert sock1 is sock2

    def test_publish_nowait_no_raise_no_subscribers(self, clean_bus):
        """publish_nowait() never raises, even with no subscribers."""
        bus = TraceBus.singleton()
        event = {"event": "test.event", "value": 42}
        # Should not raise
        bus.publish_nowait(event)

    def test_publish_nowait_handles_broken_pipe(self, clean_bus):
        """publish_nowait() gracefully removes sockets on BrokenPipeError."""
        bus = TraceBus.singleton()

        # Mock a broken socket
        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = BrokenPipeError("broken pipe")
        bus._subscribers = [mock_sock]

        event = {"event": "test.event"}
        bus.publish_nowait(event)

        # Broken socket should be removed
        assert mock_sock not in bus._subscribers

    def test_publish_nowait_handles_connection_reset(self, clean_bus):
        """publish_nowait() gracefully removes sockets on ConnectionResetError."""
        bus = TraceBus.singleton()

        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = ConnectionResetError("reset")
        bus._subscribers = [mock_sock]

        event = {"event": "test.event"}
        bus.publish_nowait(event)

        assert mock_sock not in bus._subscribers

    def test_publish_nowait_handles_generic_exception(self, clean_bus):
        """publish_nowait() gracefully handles unexpected exceptions."""
        bus = TraceBus.singleton()

        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = RuntimeError("something went wrong")
        bus._subscribers = [mock_sock]

        event = {"event": "test.event"}
        # Should not raise
        bus.publish_nowait(event)

        # Socket should be removed
        assert mock_sock not in bus._subscribers

    def test_publish_nowait_serializes_to_json(self, clean_bus):
        """publish_nowait() serializes event dict to JSON."""
        bus = TraceBus.singleton()

        mock_sock = MagicMock()
        bus._subscribers = [mock_sock]

        event = {"event": "test.event", "value": 42, "name": "test"}
        bus.publish_nowait(event)

        # Check that sendall was called
        assert mock_sock.sendall.called
        # Get the bytes that were sent
        call_args = mock_sock.sendall.call_args
        sent_bytes = call_args[0][0]
        sent_str = sent_bytes.decode("utf-8")

        # Should be NDJSON (one line)
        lines = sent_str.strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event"] == "test.event"
        assert parsed["value"] == 42

    def test_publish_nowait_appends_newline(self, clean_bus):
        """publish_nowait() appends newline to each event."""
        bus = TraceBus.singleton()

        mock_sock = MagicMock()
        bus._subscribers = [mock_sock]

        event = {"event": "test.event"}
        bus.publish_nowait(event)

        sent_bytes = mock_sock.sendall.call_args[0][0]
        sent_str = sent_bytes.decode("utf-8")
        assert sent_str.endswith("\n")

    def test_reset_clears_singleton(self, clean_bus):
        """reset() clears the singleton instance."""
        bus1 = TraceBus.singleton()
        TraceBus.reset()
        bus2 = TraceBus.singleton()
        assert bus1 is not bus2

    def test_reset_closes_sockets(self, clean_bus):
        """reset() closes all subscriber sockets."""
        bus = TraceBus.singleton()

        mock_sock = MagicMock()
        bus._subscribers = [mock_sock]

        TraceBus.reset()

        # Socket should have been closed
        assert mock_sock.close.called


class TestBusProcessor:
    """Test the structlog bus_processor."""

    def test_bus_processor_returns_event_dict_unchanged(self, clean_bus):
        """bus_processor returns the event_dict unmodified."""
        event_dict = {"event": "test", "value": 42}
        result = bus_processor(None, "info", event_dict)
        assert result is event_dict
        assert result["event"] == "test"

    def test_bus_processor_publishes_to_bus(self, clean_bus):
        """bus_processor calls bus.publish_nowait()."""
        bus = TraceBus.singleton()
        bus.publish_nowait = MagicMock()

        event_dict = {"event": "test.event", "value": 123}
        bus_processor(None, "info", event_dict)

        # Should have called publish_nowait with a dict copy
        assert bus.publish_nowait.called
        call_args = bus.publish_nowait.call_args[0][0]
        assert call_args["event"] == "test.event"

    def test_bus_processor_never_raises(self, clean_bus):
        """bus_processor never raises, even on exception."""
        bus = TraceBus.singleton()
        bus.publish_nowait = MagicMock(side_effect=RuntimeError("test error"))

        event_dict = {"event": "test"}
        # Should not raise
        result = bus_processor(None, "info", event_dict)
        assert result is event_dict

    def test_bus_processor_with_nested_dict(self, clean_bus):
        """bus_processor handles nested dicts."""
        bus = TraceBus.singleton()
        bus.publish_nowait = MagicMock()

        event_dict = {
            "event": "test",
            "nested": {"key": "value"},
            "list": [1, 2, 3],
        }
        result = bus_processor(None, "info", event_dict)
        assert result is event_dict
        assert bus.publish_nowait.called
