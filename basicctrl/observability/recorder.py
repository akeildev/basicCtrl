"""RecorderDriver — async control of ScreenRecorder.swift via IPC.

Handles start/stop of H.265 recording, writes frame metadata via SessionWriter.
Integrates with action dispatcher to map steps ↔ frame boundaries.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from basicctrl.observability.session_storage import SessionWriter
from basicctrl.visualizer.models import ReplayFrameMetadata

logger = logging.getLogger(__name__)


class RecorderDriver:
    """Async recorder control — starts/stops ScreenRecorder.swift via IPC."""

    # Unix socket path for ScreenRecorder IPC (mirrors Visualizer socket)
    RECORDER_SOCKET_PATH = "/tmp/cua-recorder.sock"

    def __init__(self, session_writer: SessionWriter):
        """Initialize recorder driver.

        Args:
            session_writer: SessionWriter instance (for metadata persistence)
        """
        self.writer = session_writer
        self.recording = False
        self.frame_idx: int = 0
        self.current_step_idx: Optional[int] = None
        self.socket_path = self.RECORDER_SOCKET_PATH

    async def start(self, overlay_window_id: int) -> None:
        """Start recording via ScreenRecorder.swift.

        Args:
            overlay_window_id: CGWindowID of visualizer panel (for SCContentFilter exclusion)

        Raises:
            RuntimeError: If ScreenRecorder.swift IPC fails or permission denied
        """
        self.recording = True
        self.frame_idx = 0
        self.current_step_idx = None

        # Send start command to ScreenRecorder sidecar
        try:
            await self._send_recorder_command({
                "cmd": "start_recording",
                "session_id": self.writer.session_id,
                "overlay_window_id": overlay_window_id,
            })
            logger.info(
                "Recording started",
                extra={
                    "session_id": self.writer.session_id,
                    "overlay_window_id": overlay_window_id,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to start recording: %s",
                e,
                extra={"session_id": self.writer.session_id},
            )
            self.recording = False
            raise RuntimeError(f"Failed to start recording: {e}") from e

    async def stop(self) -> None:
        """Stop recording.

        Waits for ScreenRecorder to finalize .mov + metadata files.
        """
        if not self.recording:
            return

        self.recording = False

        try:
            await self._send_recorder_command({"cmd": "stop_recording"})
            logger.info("Recording stopped", extra={"session_id": self.writer.session_id})
        except Exception as e:
            logger.error(
                "Failed to stop recording: %s",
                e,
                extra={"session_id": self.writer.session_id},
            )

    async def write_frame_metadata(
        self,
        frame_idx: int,
        step_idx: Optional[int] = None,
        timestamp_ms: Optional[int] = None,
    ) -> None:
        """Write frame metadata to recording_metadata.ndjson.

        Called for each frame captured (60fps), or on step boundaries.

        Args:
            frame_idx: Frame index (0-indexed)
            step_idx: Associated action step (null between steps)
            timestamp_ms: Session-relative milliseconds (auto-generated if None)
        """
        if not self.recording:
            return

        if timestamp_ms is None:
            timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        frame = ReplayFrameMetadata(
            frame_idx=frame_idx,
            step_idx=step_idx,
            timestamp_ms=timestamp_ms,
        )
        self.writer.write_recording_metadata(frame)
        self.frame_idx = frame_idx

    def update_step_id(self, step_idx: Optional[int]) -> None:
        """Update the current step ID for frame↔step mapping.

        Called by action dispatcher when a new step begins (action fires).

        Args:
            step_idx: Current action step index, or None if between actions
        """
        self.current_step_idx = step_idx

    # MARK: - Private Helpers

    async def _send_recorder_command(self, command: dict) -> None:
        """Send NDJSON command to ScreenRecorder.swift sidecar.

        Args:
            command: Dictionary to serialize as NDJSON

        Raises:
            RuntimeError: If socket connection fails
        """
        try:
            # Try to connect to recorder socket
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=5.0,
            )

            # Send command as NDJSON
            json_str = json.dumps(command, separators=(",", ":"), default=str)
            writer.write((json_str + "\n").encode("utf-8"))
            await writer.drain()

            # Read response (simple handshake)
            response_data = await asyncio.wait_for(reader.read(256), timeout=2.0)
            response_str = response_data.decode("utf-8", errors="ignore").strip()

            if response_str:
                logger.debug("Recorder response: %s", response_str)

            writer.close()
            await writer.wait_closed()

        except FileNotFoundError:
            raise RuntimeError(
                f"ScreenRecorder sidecar not running (socket {self.socket_path} not found)"
            )
        except asyncio.TimeoutError as e:
            raise RuntimeError(f"ScreenRecorder IPC timeout: {e}")
        except Exception as e:
            raise RuntimeError(f"ScreenRecorder IPC error: {e}")


class RecorderTelemetry:
    """Per-frame performance telemetry for H.265 encoder.

    Logs encode latency, frame drops, quality metrics.
    """

    def __init__(self, session_writer: SessionWriter):
        self.writer = session_writer
        self.frame_count: int = 0
        self.dropped_frames: int = 0
        self.total_encode_ms: float = 0.0

    def record_frame_encoded(self, encode_latency_ms: float) -> None:
        """Record a successfully encoded frame.

        Args:
            encode_latency_ms: Time to encode frame (H.265 VTCompressionSession callback latency)
        """
        self.frame_count += 1
        self.total_encode_ms += encode_latency_ms

        if encode_latency_ms > 16.0:
            logger.warning(
                "Frame encode latency exceeded budget: %.1fms (>16ms target)",
                encode_latency_ms,
            )

    def record_frame_dropped(self) -> None:
        """Record a frame drop (encoder couldn't keep up)."""
        self.dropped_frames += 1
        logger.warning(
            "Frame dropped by H.265 encoder (total drops: %d)",
            self.dropped_frames,
        )

    def summary(self) -> dict:
        """Return telemetry summary for logging/reporting.

        Returns:
            Dict with frame_count, dropped_frames, avg_encode_ms
        """
        avg_encode_ms = (
            self.total_encode_ms / self.frame_count if self.frame_count > 0 else 0.0
        )
        return {
            "frame_count": self.frame_count,
            "dropped_frames": self.dropped_frames,
            "avg_encode_ms": round(avg_encode_ms, 2),
            "drop_rate": (
                round(self.dropped_frames / self.frame_count * 100, 1)
                if self.frame_count > 0
                else 0.0
            ),
        }
