"""Phase 5 visualizer tests — importorskip until Swift sidecar lands."""
import json

import pytest

# Wave 0: soft import, skip if not ready
pytest.importorskip("cua_overlay.visualizer")

from cua_overlay.observability.session_storage import SessionWriter
from cua_overlay.visualizer.models import (
    ActionChannel,
    ActionTier,
    CounterfactualState,
    DiffLine,
    DiffMarker,
    GhostCursorCommand,
    HighlightBoxCommand,
    HUDActionEntry,
    HUDCommand,
    ReplayFrameMetadata,
    VerificationStatus,
)


class TestImportSkip:
    """Verify pytest.importorskip gate works."""

    def test_models_import(self):
        """Pydantic schemas import cleanly."""
        assert GhostCursorCommand is not None
        assert ReplayFrameMetadata is not None


class TestModelValidation:
    """Pydantic schema validation."""

    def test_ghost_cursor_command_valid(self):
        """GhostCursorCommand accepts valid coords and duration."""
        cmd = GhostCursorCommand(
            x=100.5, y=200.3, duration_ms=250, timestamp_ns=1000
        )
        assert cmd.x == 100.5
        assert cmd.y == 200.3
        assert cmd.duration_ms == 250
        assert cmd.cmd == "ghost_cursor"

    def test_ghost_cursor_duration_bounds(self):
        """GhostCursorCommand enforces 150-350ms duration (UI-SPEC L72)."""
        with pytest.raises(ValueError):
            GhostCursorCommand(x=100, y=100, duration_ms=100, timestamp_ns=1000)
        with pytest.raises(ValueError):
            GhostCursorCommand(x=100, y=100, duration_ms=400, timestamp_ns=1000)

    def test_hud_action_entry_label_truncate(self):
        """HUDActionEntry enforces max_length=40 (UI-SPEC L145)."""
        entry = HUDActionEntry(
            action_type="click",
            target_label="Short label",
            tier=ActionTier.T1,
            channel=ActionChannel.C2,
            status=VerificationStatus.VERIFIED,
        )
        assert len(entry.target_label) <= 40

        # Over 40 chars should fail validation
        with pytest.raises(ValueError):
            HUDActionEntry(
                action_type="click",
                target_label="x" * 41,
                tier=ActionTier.T1,
                channel=ActionChannel.C2,
                status=VerificationStatus.VERIFIED,
            )

    def test_replay_frame_metadata_schema(self):
        """ReplayFrameMetadata matches recording_metadata.ndjson schema (RESEARCH L174-185)."""
        frame = ReplayFrameMetadata(frame_idx=10, step_idx=5, timestamp_ms=1000)
        assert frame.frame_idx == 10
        assert frame.step_idx == 5
        assert frame.capture_error is None

        # Between-step frame has null step_idx
        between = ReplayFrameMetadata(frame_idx=11, timestamp_ms=1001)
        assert between.step_idx is None


class TestSessionWriter:
    """Observability session storage."""

    def test_session_writer_init(self, tmp_path):
        """SessionWriter creates directory structure."""
        import os

        os.environ["HOME"] = str(tmp_path)

        writer = SessionWriter("test-session")
        assert writer.session_dir.exists()
        assert (writer.session_dir / "state_snapshots").exists()
        assert (writer.session_dir / "cassettes").exists()
        assert (writer.session_dir / "recordings").exists()

    def test_session_version_file(self, tmp_path):
        """SessionWriter writes _version.json (RESEARCH L188-197)."""
        import os

        os.environ["HOME"] = str(tmp_path)

        writer = SessionWriter("test-session")
        version_path = writer.session_dir / "_version.json"
        assert version_path.exists()

        with open(version_path) as f:
            version = json.load(f)
        assert version["format"] == 1
        assert "schema_updated" in version
        assert "fields" in version

    def test_write_log_line(self, tmp_path):
        """SessionWriter.write_log_line appends NDJSON."""
        import os

        os.environ["HOME"] = str(tmp_path)

        writer = SessionWriter("test-session")
        event = {"event": "test_action", "step_idx": 0, "status": "VERIFIED"}
        writer.write_log_line(event)

        # Verify NDJSON written
        assert writer._action_log_path.exists()
        with open(writer._action_log_path) as f:
            line = f.readline()
        parsed = json.loads(line)
        assert parsed["event"] == "test_action"


# Placeholder test functions to be filled by Wave 1-6
# These will fail until Swift sidecar + Python driver code is implemented


@pytest.mark.skip(reason="Wave 1 — Swift Visualizer.swift")
def test_ghost_cursor_lerp_timing():
    """VIS-01: Ghost cursor lerps to target before action fires."""
    pass


@pytest.mark.skip(reason="Wave 2 — SwiftUI HUD.swift")
def test_hud_action_history_snapshot():
    """VIS-02: HUD displays last 8 actions with T1-T5/C1-C5 badges."""
    pass


@pytest.mark.skip(reason="Wave 1 — SCContentFilter integration")
def test_scontent_filter_excludes_overlay():
    """VIS-03, VIS-05: SCContentFilter(excludingWindows:) excludes overlay."""
    pass


@pytest.mark.skip(reason="Wave 4 — Replay engine")
def test_replay_state_reconstruction():
    """VIS-04, OBS-04: Replay reconstructs StateNode from action_log + video."""
    pass


@pytest.mark.skip(reason="Wave 2 — HUD hotkey handling")
def test_hotkey_hud_toggle():
    """VIS-06: Cmd+Shift+V toggles, opacity slider, position snap."""
    pass


@pytest.mark.skip(reason="Wave 3 — ScreenRecorder.swift")
def test_h265_recording_creation():
    """OBS-01: 60fps H.265 recording at ~/.cua/sessions/<id>/recording.mov."""
    pass


@pytest.mark.skip(reason="Wave 0/1 — structlog integration")
def test_action_log_ndjson_structured():
    """OBS-02: action_log.ndjson persisted via structlog."""
    pass


@pytest.mark.skip(reason="Wave 5 — 3D timeline")
def test_timeline_1000_nodes_60fps():
    """OBS-03: 3D timeline renders 1000+ nodes without frame drop."""
    pass


@pytest.mark.skip(reason="Wave 4 — Replay engine")
def test_scrub_alignment_frame_accuracy():
    """OBS-04: Replay scrub matches action_log boundaries ±1 frame."""
    pass


@pytest.mark.skip(reason="Wave 5 — Counterfactual renderer")
def test_counterfactual_dashed_path_snapshot():
    """OBS-05: Counterfactual path renders dashed in post-divergence states."""
    pass


@pytest.mark.skip(reason="Wave 5 — Session differ")
def test_diff_alignment_lcs():
    """OBS-06: Diff view aligns sessions via LCS, highlights heals."""
    pass
