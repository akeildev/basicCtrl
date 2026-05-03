"""Python driver for HUD updates — assembles commands and sends to Visualizer.swift via unix socket."""
from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import structlog

from cua_overlay.visualizer.models import (
    HUDCommand,
    HUDActionEntry,
    ActionTier,
    ActionChannel,
    VerificationStatus,
)


class HUDDriver:
    """Sends HUD updates to Swift visualizer sidecar via unix socket."""

    SOCKET_PATH = Path("/tmp/cua-visualizer.sock")

    def __init__(self):
        """Initialize HUD driver with empty action history."""
        self.action_history: list[HUDActionEntry] = []
        self.session_start_iso = ""
        self.current_goal = ""

    def set_session_metadata(self, session_start_iso: str, goal: str) -> None:
        """Update session timestamp and goal prompt."""
        self.session_start_iso = session_start_iso
        self.current_goal = goal[:40]  # Truncate per UI-SPEC

    def append_action(
        self,
        action_type: str,
        target_label: str,
        tier: ActionTier,
        channel: ActionChannel,
        status: VerificationStatus,
        status_detail: Optional[str] = None,
    ) -> None:
        """Append action to history (max 8 kept)."""
        entry = HUDActionEntry(
            action_type=action_type,
            target_label=target_label[:40],  # Truncate
            tier=tier,
            channel=channel,
            status=status,
            status_detail=status_detail,
        )
        self.action_history.append(entry)
        # Keep only last 8
        if len(self.action_history) > 8:
            self.action_history = self.action_history[-8:]

    def send_hud_update(self) -> None:
        """Send HUD command to Swift visualizer via unix socket."""
        log = structlog.get_logger()
        cmd = HUDCommand(
            entries=self.action_history,
            session_start_iso=self.session_start_iso,
            goal=self.current_goal,
            timestamp_ns=int(datetime.now(timezone.utc).timestamp() * 1e9),
        )

        log.debug(
            "viz.send_attempt",
            num_entries=len(self.action_history),
        )

        try:
            # Convert Pydantic model to JSON
            json_str = cmd.model_dump_json()

            # Connect to socket and send
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(self.SOCKET_PATH))
            log.debug("viz.socket_connected")
            sock.sendall((json_str + "\n").encode("utf-8"))
            sock.close()
            log.debug("viz.frame_rendered")
        except (FileNotFoundError, ConnectionRefusedError, BrokenPipeError) as e:
            # Socket not ready yet (Wave 1 still building) — log but continue
            log.debug(
                "viz.send_failed",
                error=type(e).__name__,
                reason="socket_not_ready",
            )
        except Exception as e:
            # Other errors — log and continue (HUD is non-critical)
            log.debug(
                "viz.send_failed",
                error=type(e).__name__,
                reason=str(e)[:100],
            )

    def clear_history(self) -> None:
        """Clear all actions from HUD."""
        self.action_history = []
        self.send_hud_update()
