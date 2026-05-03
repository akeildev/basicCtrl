"""Replay engine — reconstruct StateNode at every step from action_log.ndjson."""
import json
from pathlib import Path
from typing import Optional, Any

from cua_overlay.observability.session_storage import SessionWriter


class ReplayEngine:
    """Loads action_log.ndjson + recording_metadata.ndjson, reconstructs state deterministically."""

    def __init__(self, session_id: str):
        self.session_dir = Path.home() / ".cua" / "sessions" / session_id
        self.action_log_path = self.session_dir / "action_log.ndjson"
        self.metadata_path = self.session_dir / "recording_metadata.ndjson"
        self.actions = []
        self.metadata = []
        self._load()

    def _load(self) -> None:
        """Load action_log + metadata NDJSON."""
        if self.action_log_path.exists():
            with open(self.action_log_path) as f:
                for line in f:
                    if line.strip():
                        self.actions.append(json.loads(line))

        if self.metadata_path.exists():
            with open(self.metadata_path) as f:
                for line in f:
                    if line.strip():
                        self.metadata.append(json.loads(line))

    def get_state_at_step(self, step_idx: int) -> Optional[dict]:
        """Reconstruct StateNode at given step by replaying all prior actions."""
        state = {}

        for action in self.actions[:step_idx + 1]:
            if "hoare_post" in action:
                state.update(action["hoare_post"].get("state_delta", {}))

        return state

    def get_frame_for_step(self, step_idx: int) -> Optional[int]:
        """Lookup frame_idx from recording_metadata.ndjson for given step_idx."""
        for entry in self.metadata:
            if entry.get("step_idx") == step_idx:
                return entry.get("frame_idx")
        return None

    def scrub_to_step(self, step_idx: int) -> tuple[int, dict]:
        """Return (frame_idx, reconstructed_state) for scrubbing."""
        frame = self.get_frame_for_step(step_idx)
        state = self.get_state_at_step(step_idx)
        return (frame or 0, state or {})
