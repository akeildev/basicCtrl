"""Phase 5 visualizer tests — importorskip until Swift sidecar lands."""
import json

import pytest

# Wave 0: soft import, skip if not ready
pytest.importorskip("basicctrl.visualizer")

from basicctrl.observability.session_storage import SessionWriter
from basicctrl.visualizer.models import (
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


# =============================================================================
# VIS-01: Ghost Cursor Lerp Timing
# =============================================================================


@pytest.mark.integration
def test_ghost_cursor_lerp_timing():
    """VIS-01: Ghost cursor lerps to target before action fires (150-350ms).

    Verifies:
    - GhostCursorCommand created with valid coordinates
    - duration_ms enforced within [150, 350]ms range
    - Command serializes to JSON for IPC
    """
    # Create valid command with target coordinates
    cmd = GhostCursorCommand(
        x=500.5,
        y=300.2,
        duration_ms=250,
        timestamp_ns=1000000000,
    )

    # Verify fields
    assert cmd.x == 500.5
    assert cmd.y == 300.2
    assert cmd.duration_ms == 250
    assert 150 <= cmd.duration_ms <= 350

    # Verify serialization
    json_str = cmd.model_dump_json()
    assert "ghost_cursor" in json_str
    assert "500.5" in json_str


# =============================================================================
# VIS-02: HUD Action History Snapshot
# =============================================================================


@pytest.mark.integration
def test_hud_action_history_snapshot():
    """VIS-02: HUD displays last 8 actions with T1-T5/C1-C5 badges.

    Verifies:
    - HUDDriver maintains max 8 action history (ring buffer)
    - Each entry has tier/channel badges
    - Entries ordered by recency (oldest first, newest last)
    - Serialization includes all fields
    """
    from basicctrl.visualizer.hud_driver import HUDDriver

    driver = HUDDriver()
    driver.set_session_metadata(
        session_start_iso="2026-05-01T20:00:00Z",
        goal="Test task"
    )

    # Add 10 actions — should only keep last 8
    for i in range(10):
        driver.append_action(
            action_type="click",
            target_label=f"Button {i}",
            tier=ActionTier.T1 if i % 2 == 0 else ActionTier.T2,
            channel=ActionChannel.C2 if i % 2 == 0 else ActionChannel.C5,
            status=VerificationStatus.VERIFIED,
        )

    # Verify exactly 8 entries
    assert len(driver.action_history) == 8

    # Verify all entries have tier + channel badges
    for entry in driver.action_history:
        assert entry.tier in [ActionTier.T1, ActionTier.T2, ActionTier.T3, ActionTier.T4, ActionTier.T5]
        assert entry.channel in [ActionChannel.C1, ActionChannel.C2, ActionChannel.C3, ActionChannel.C4, ActionChannel.C5]
        assert entry.status == VerificationStatus.VERIFIED

    # Verify ring buffer kept newest items (labels 2-9, which map to indices 2..9)
    assert driver.action_history[0].target_label == "Button 2"
    assert driver.action_history[-1].target_label == "Button 9"


# =============================================================================
# VIS-03 / VIS-05: SCContentFilter Excludes Overlay
# =============================================================================


@pytest.mark.integration
def test_scontent_filter_excludes_overlay():
    """VIS-03, VIS-05: SCContentFilter(excludingWindows:) filters out overlay.

    Verifies:
    - Visualizer.swift contains SCContentFilter usage
    - excludingWindows parameter present
    - No sharingType=.none (macOS 15+ deprecated)

    This is a pure Python test checking grep assertions on Swift source.
    Hardware-gated tests skipped if visual verification needed.
    """
    import subprocess
    from pathlib import Path

    swift_file = Path("libs/cua-driver/App/Visualizer.swift")
    assert swift_file.exists(), "Visualizer.swift not found"

    # Check for SCContentFilter presence
    result = subprocess.run(
        ["grep", "-c", "SCContentFilter", str(swift_file)],
        capture_output=True,
    )
    count = int(result.stdout.decode().strip() or "0")
    assert count >= 1, "SCContentFilter not found in Visualizer.swift"

    # Check that sharingType=.none is NOT present
    result = subprocess.run(
        ["grep", "-c", "sharingType.*\\.none", str(swift_file)],
        capture_output=True,
    )
    count = int(result.stdout.decode().strip() or "0")
    assert count == 0, "sharingType=.none found (macOS 15+ deprecated)"


# =============================================================================
# VIS-06: Hotkey HUD Toggle
# =============================================================================


@pytest.mark.integration
def test_hotkey_hud_toggle():
    """VIS-06: Cmd+Shift+V hotkey toggles HUD visibility.

    Verifies:
    - HotKeyCommand model accepts hotkey events
    - toggle_hud action serializable
    - Timestamp in nanoseconds
    """
    from basicctrl.visualizer.models import HotKeyCommand
    from datetime import datetime, timezone

    # Simulate Cmd+Shift+V hotkey event
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)

    cmd = HotKeyCommand(
        binding="cmd+shift+v",
        action="toggle_hud",
        timestamp_ns=now_ns,
    )

    assert cmd.cmd == "hotkey"
    assert cmd.binding == "cmd+shift+v"
    assert cmd.action == "toggle_hud"
    assert cmd.timestamp_ns == now_ns

    # Verify serialization
    json_str = cmd.model_dump_json()
    assert "hotkey" in json_str
    assert "toggle_hud" in json_str
