"""Visualizer driver — sends commands to Swift sidecar over unix socket.

Async socket client for IPC to Visualizer.swift. Supports ghost cursor,
highlight box, and HUD action commands. Silent-fail mode: if socket not
present, logs at DEBUG and returns (visualizer is optional, non-critical).

All commands serialized as NDJSON and sent over /tmp/cua-visualizer.sock.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import structlog

from cua_overlay.visualizer.models import (
    GhostCursorCommand,
    HighlightBoxCommand,
)

_log = structlog.get_logger()


class VisualizerBus:
    """Unix socket IPC client to Visualizer.swift."""

    SOCKET_PATH = Path("/tmp/cua-visualizer.sock")

    @staticmethod
    async def send_command(cmd: dict) -> None:
        """Send NDJSON command to visualizer.

        Silent-failure: if socket not present or connection fails,
        log at DEBUG and return. Visualizer is optional and must not
        block the orchestrator.
        """
        try:
            reader, writer = await asyncio.open_unix_connection(
                str(VisualizerBus.SOCKET_PATH)
            )
            json_str = json.dumps(cmd)
            writer.write((json_str + "\n").encode("utf-8"))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except FileNotFoundError:
            _log.debug(
                "visualizer.socket_not_found",
                socket_path=str(VisualizerBus.SOCKET_PATH),
            )
        except ConnectionRefusedError:
            _log.debug(
                "visualizer.connection_refused",
                socket_path=str(VisualizerBus.SOCKET_PATH),
            )
        except BrokenPipeError:
            _log.debug("visualizer.broken_pipe")
        except Exception as exc:
            _log.debug(
                "visualizer.send_failed",
                error=str(exc),
                cmd_type=cmd.get("cmd"),
            )

    @staticmethod
    async def send_ghost_cursor(x: float, y: float, duration_ms: int) -> None:
        """Animate ghost cursor to target.

        Args:
            x: Target center X coordinate.
            y: Target center Y coordinate.
            duration_ms: Lerp duration in milliseconds (150-350 per UI-SPEC).
        """
        try:
            cmd = GhostCursorCommand(
                x=x,
                y=y,
                duration_ms=duration_ms,
                timestamp_ns=int(time.time_ns()),
            )
            await VisualizerBus.send_command(cmd.model_dump())
        except Exception as exc:
            _log.debug(
                "visualizer.send_ghost_cursor_failed",
                error=str(exc),
            )

    @staticmethod
    async def send_highlight(
        bbox_x: float,
        bbox_y: float,
        bbox_width: float,
        bbox_height: float,
        label: str,
        tier: str,
        channel: str,
    ) -> None:
        """Show element highlight box.

        Args:
            bbox_x: Bounding box top-left X.
            bbox_y: Bounding box top-left Y.
            bbox_width: Bounding box width.
            bbox_height: Bounding box height.
            label: Element label (max 40 chars, will be truncated).
            tier: Action tier (T1-T5).
            channel: Action channel (C1-C5).
        """
        try:
            cmd = HighlightBoxCommand(
                bbox_x=bbox_x,
                bbox_y=bbox_y,
                bbox_width=bbox_width,
                bbox_height=bbox_height,
                label=label[:40],  # Truncate per UI-SPEC
                tier=tier,
                channel=channel,
                timestamp_ns=int(time.time_ns()),
            )
            await VisualizerBus.send_command(cmd.model_dump())
        except Exception as exc:
            _log.debug(
                "visualizer.send_highlight_failed",
                error=str(exc),
            )
