"""SessionWriter — persistent storage for action_log, state snapshots, recording metadata."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from basicctrl.visualizer.models import ReplayFrameMetadata


class PerformanceMetrics(BaseModel, frozen=True):
    """Per-step performance telemetry."""

    step_idx: int
    elapsed_ms: float  # Total action time (action + verify)
    translator_name: str
    channel_name: str
    verifier_latency_ms: float
    timestamp_ns: int


class SessionWriter:
    """Persistent session storage for Phase 5 + Phase 1-4 integration."""

    BASE_DIR = Path.home() / ".cua" / "sessions"

    def __init__(self, session_id: str):
        """Initialize session directory structure."""
        self.session_id = session_id
        self.session_dir = self.BASE_DIR / session_id

        # Create all subdirectories
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "state_snapshots").mkdir(exist_ok=True)
        (self.session_dir / "cassettes").mkdir(exist_ok=True)
        (self.session_dir / "recordings").mkdir(exist_ok=True)

        # Write versioning metadata
        self._write_version_file()

        # File handles
        self._action_log_path = self.session_dir / "action_log.ndjson"
        self._recording_metadata_path = self.session_dir / "recording_metadata.ndjson"
        self._heals_path = self.session_dir / "heals.ndjson"

    def _write_version_file(self) -> None:
        """Write _version.json with schema info."""
        version_data = {
            "format": 1,
            "schema_updated": datetime.now(timezone.utc).isoformat(),
            "fields": {
                "recording_metadata": "frame_idx, step_idx, timestamp_ms, capture_error",
                "action_log": "standard Phase 1-4 schema + Phase 5 recording refs",
                "state_snapshots": "full StateNode from HoarePost",
            },
        }
        version_path = self.session_dir / "_version.json"
        with open(version_path, "w") as f:
            json.dump(version_data, f, indent=2)

    def write_log_line(self, event_dict: dict) -> None:
        """Append NDJSON line to action_log.ndjson (called by structlog)."""
        with open(self._action_log_path, "a") as f:
            f.write(json.dumps(event_dict, separators=(",", ":"), default=str) + "\n")

    def write_state_snapshot(self, step_idx: int, state_node: dict) -> None:
        """Write StateNode JSON to state_snapshots/{step_idx}.json."""
        snap_path = self.session_dir / "state_snapshots" / f"{step_idx}.json"
        with open(snap_path, "w") as f:
            json.dump(state_node, f, indent=2, default=str)

    def write_recording_metadata(self, frame: ReplayFrameMetadata) -> None:
        """Append frame metadata to recording_metadata.ndjson."""
        with open(self._recording_metadata_path, "a") as f:
            f.write(frame.model_dump_json(exclude_none=True) + "\n")

    def write_heal_event(self, heal_event: dict) -> None:
        """Append heal event to heals.ndjson (Phase 3 integration)."""
        with open(self._heals_path, "a") as f:
            f.write(json.dumps(heal_event, separators=(",", ":"), default=str) + "\n")

    def finalize_session(self) -> None:
        """Called on session end. Future: sync to cloud, compress, etc."""
        pass  # Placeholder for Phase 6 durability hardening
