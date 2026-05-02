"""TraceBus — structlog processor that broadcasts events to live subscribers via unix socket.

Best-effort event distribution to /tmp/cua-trace-bus.sock. Multiple subscribers
can connect and receive NDJSON event stream. No blocking, no raising.
"""
from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Any, MutableMapping

import structlog


class TraceBus:
    """Unix socket server for live event streaming.

    Singleton: one bus per process. Subscribers connect to /tmp/cua-trace-bus.sock
    and receive NDJSON event stream (one event per line).

    Architecture:
      - Constructor opens socket in non-blocking mode
      - publish_nowait() sends to all connected clients; never blocks, never raises
      - Catch all exceptions and continue
    """

    _instance: TraceBus | None = None
    _socket_path = Path("/tmp/cua-trace-bus.sock")

    def __init__(self):
        """Initialize the bus (called once via singleton())."""
        self._server_socket: socket.socket | None = None
        self._subscribers: list[socket.socket] = []
        self._log = structlog.get_logger()

    @classmethod
    def singleton(cls) -> TraceBus:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._init_socket()
        return cls._instance

    def _init_socket(self) -> None:
        """Lazily initialize unix socket server (idempotent)."""
        if self._server_socket is not None:
            return
        try:
            # Clean up stale socket file
            if self._socket_path.exists():
                self._socket_path.unlink()

            # Create unix socket server
            self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(str(self._socket_path))
            self._server_socket.listen(5)
            self._server_socket.setblocking(False)

            self._log.debug("trace_bus.socket_opened", path=str(self._socket_path))
        except Exception as e:
            # Socket init failed — bus stays disabled, no raise
            self._log.debug(
                "trace_bus.socket_init_failed",
                error=str(e),
                path=str(self._socket_path),
            )
            self._server_socket = None

    def _accept_pending(self) -> None:
        """Non-blocking accept of all pending connections."""
        if self._server_socket is None:
            return
        try:
            while True:
                client_sock, _ = self._server_socket.accept()
                client_sock.setblocking(False)
                self._subscribers.append(client_sock)
        except (BlockingIOError, socket.timeout):
            # No more pending connections
            pass
        except Exception as e:
            self._log.debug("trace_bus.accept_failed", error=str(e))

    def publish_nowait(self, event_dict: dict[str, Any]) -> None:
        """Broadcast event to all subscribers (best-effort, never blocks).

        Accepts pending connections, sends NDJSON to all subscribers,
        cleans up closed sockets. Catch all exceptions.
        """
        if self._server_socket is None:
            return

        try:
            # Try to accept new connections
            self._accept_pending()

            # Serialize event as NDJSON
            json_line = json.dumps(event_dict, separators=(",", ":"), default=str)
            msg = (json_line + "\n").encode("utf-8")

            # Send to all subscribers; remove those that fail
            stale = []
            for sock in self._subscribers:
                try:
                    sock.sendall(msg)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # Socket closed on other end
                    stale.append(sock)
                except Exception as e:
                    # Other errors — still remove the socket
                    self._log.debug("trace_bus.send_failed", error=str(e))
                    stale.append(sock)

            # Clean up stale sockets
            for sock in stale:
                try:
                    sock.close()
                except Exception:
                    pass
                self._subscribers.remove(sock)
        except Exception as e:
            # Catch-all: never raise from publish_nowait
            self._log.debug("trace_bus.publish_failed", error=str(e))

    @classmethod
    def reset(cls) -> None:
        """Close and reset singleton (for testing)."""
        if cls._instance is not None:
            try:
                if cls._instance._server_socket is not None:
                    cls._instance._server_socket.close()
                for sock in cls._instance._subscribers:
                    try:
                        sock.close()
                    except Exception:
                        pass
            except Exception:
                pass
            cls._instance = None


def bus_processor(
    _logger: Any,
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor that publishes to TraceBus (best-effort, never blocks).

    Install via:
        processors.append(bus_processor)

    This processor is called AFTER redaction and timestamping, so event_dict
    is clean and has timing info.
    """
    try:
        bus = TraceBus.singleton()
        bus.publish_nowait(dict(event_dict))
    except Exception:
        # Never raise from processor
        pass

    return event_dict
