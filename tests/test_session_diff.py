"""Unit tests for session diff LCS alignment and heal event detection."""
import json
import tempfile
from pathlib import Path

import pytest

from basicctrl.replay.diff import (
    DiffRow,
    SessionDiffer,
    lcs_alignment,
)


class TestLCSAlignment:
    """Test longest common subsequence alignment."""

    def test_lcs_identical_sequences(self):
        """LCS of identical sequences returns all matched pairs."""
        a = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
            {"app": "Mail", "target_label": "To", "action_type": "type"},
        ]
        b = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
            {"app": "Mail", "target_label": "To", "action_type": "type"},
        ]
        align = lcs_alignment(a, b)
        assert align == [(0, 0), (1, 1)]

    def test_lcs_removed_step(self):
        """LCS with removed step shows (i, None) alignment."""
        a = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
            {"app": "Mail", "target_label": "To", "action_type": "type"},
        ]
        b = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
        ]
        align = lcs_alignment(a, b)
        assert align == [(0, 0), (1, None)]

    def test_lcs_added_step(self):
        """LCS with added step shows (None, j) alignment."""
        a = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
        ]
        b = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
            {"app": "Mail", "target_label": "Subject", "action_type": "type"},
        ]
        align = lcs_alignment(a, b)
        assert align == [(0, 0), (None, 1)]

    def test_lcs_empty_a(self):
        """LCS with empty A sequence."""
        a = []
        b = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
        ]
        align = lcs_alignment(a, b)
        assert align == [(None, 0)]

    def test_lcs_empty_b(self):
        """LCS with empty B sequence."""
        a = [
            {"app": "Mail", "target_label": "Send", "action_type": "click"},
        ]
        b = []
        align = lcs_alignment(a, b)
        assert align == [(0, None)]

    def test_lcs_both_empty(self):
        """LCS with both sequences empty."""
        a = []
        b = []
        align = lcs_alignment(a, b)
        assert align == []

    def test_lcs_match_key_only_app(self):
        """LCS matches on app, target_label, action_type tuple.

        Different tier but same tuple → treated as matched step.
        """
        a = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T1",
            },
        ]
        b = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T2",  # Different tier
            },
        ]
        align = lcs_alignment(a, b)
        # Should still match because match_key ignores tier
        assert align == [(0, 0)]


class TestSessionDifferDiffGeneration:
    """Test diff generation with heal event detection."""

    def test_diff_common_unchanged(self):
        """Diff marks unchanged matched steps as 'common'."""
        a = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
        ]
        b = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
        ]

        differ = SessionDiffer.__new__(SessionDiffer)
        differ.session_a = a
        differ.session_b = b
        differ.heals_a = []
        differ.heals_b = []

        diff = differ.generate_diff()
        assert len(diff) == 1
        assert diff[0].kind == "common"
        assert diff[0].step_idx_a == 0
        assert diff[0].step_idx_b == 0

    def test_diff_heal_event_failed_to_verified(self):
        """Diff marks verdict change failed→verified as 'heal'."""
        a = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T3",
                "verdict": "failed",
            },
        ]
        b = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
        ]

        differ = SessionDiffer.__new__(SessionDiffer)
        differ.session_a = a
        differ.session_b = b
        differ.heals_a = []
        differ.heals_b = []

        diff = differ.generate_diff()
        assert len(diff) == 1
        assert diff[0].kind == "heal"
        assert diff[0].before_verdict == "failed"
        assert diff[0].after_verdict == "verified"
        assert diff[0].heal_reason == "T3→T1"

    def test_diff_changed_tier_swap(self):
        """Diff marks tier change as 'changed'."""
        a = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T3",
                "verdict": "verified",
            },
        ]
        b = [
            {
                "app": "Mail",
                "target_label": "Send",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
        ]

        differ = SessionDiffer.__new__(SessionDiffer)
        differ.session_a = a
        differ.session_b = b
        differ.heals_a = []
        differ.heals_b = []

        diff = differ.generate_diff()
        assert len(diff) == 1
        assert diff[0].kind == "changed"
        assert diff[0].before_verdict == "verified"
        assert diff[0].after_verdict == "verified"
        assert diff[0].heal_reason == "T3→T1"

    def test_diff_removed_step(self):
        """Diff marks unmatched A step as 'removed'."""
        a = [
            {
                "app": "Mail",
                "target_label": "To",
                "action_type": "type",
                "tier": "T1",
                "verdict": "verified",
            },
        ]
        b = []

        differ = SessionDiffer.__new__(SessionDiffer)
        differ.session_a = a
        differ.session_b = b
        differ.heals_a = []
        differ.heals_b = []

        diff = differ.generate_diff()
        assert len(diff) == 1
        assert diff[0].kind == "removed"
        assert diff[0].step_idx_a == 0
        assert diff[0].step_idx_b is None

    def test_diff_added_step(self):
        """Diff marks unmatched B step as 'added'."""
        a = []
        b = [
            {
                "app": "Mail",
                "target_label": "To",
                "action_type": "type",
                "tier": "T1",
                "verdict": "verified",
            },
        ]

        differ = SessionDiffer.__new__(SessionDiffer)
        differ.session_a = a
        differ.session_b = b
        differ.heals_a = []
        differ.heals_b = []

        diff = differ.generate_diff()
        assert len(diff) == 1
        assert diff[0].kind == "added"
        assert diff[0].step_idx_a is None
        assert diff[0].step_idx_b == 0

    def test_diff_multiple_rows(self):
        """Diff with mixed common, changed, added, removed."""
        a = [
            {
                "app": "Mail",
                "target_label": "Inbox",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
            {
                "app": "Mail",
                "target_label": "Compose",
                "action_type": "click",
                "tier": "T3",
                "verdict": "failed",
            },
            {
                "app": "Mail",
                "target_label": "Subject",
                "action_type": "type",
                "tier": "T1",
                "verdict": "verified",
            },
        ]
        b = [
            {
                "app": "Mail",
                "target_label": "Inbox",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
            {
                "app": "Mail",
                "target_label": "Compose",
                "action_type": "click",
                "tier": "T1",
                "verdict": "verified",
            },
            {
                "app": "Mail",
                "target_label": "To",
                "action_type": "type",
                "tier": "T1",
                "verdict": "verified",
            },
        ]

        differ = SessionDiffer.__new__(SessionDiffer)
        differ.session_a = a
        differ.session_b = b
        differ.heals_a = []
        differ.heals_b = []

        diff = differ.generate_diff()
        assert len(diff) == 4

        # First: common (Inbox match)
        assert diff[0].kind == "common"

        # Second: healed (Compose T3→T1, failed→verified)
        assert diff[1].kind == "heal"

        # Third: removed (Subject only in A)
        assert diff[2].kind == "removed"

        # Fourth: added (To only in B)
        assert diff[3].kind == "added"


class TestDiffRowModel:
    """Test DiffRow Pydantic model."""

    def test_diff_row_frozen(self):
        """DiffRow is frozen (immutable)."""
        row = DiffRow(kind="common")
        with pytest.raises(Exception):  # Pydantic ValidationError on assignment
            row.kind = "changed"

    def test_diff_row_all_fields(self):
        """DiffRow with all fields."""
        row = DiffRow(
            kind="heal",
            step_idx_a=5,
            step_idx_b=5,
            action_a={"tier": "T3"},
            action_b={"tier": "T1"},
            before_verdict="failed",
            after_verdict="verified",
            heal_reason="T3→T1",
        )
        assert row.kind == "heal"
        assert row.step_idx_a == 5
        assert row.before_verdict == "failed"
        assert row.heal_reason == "T3→T1"


class TestSessionDifferLoadSession:
    """Test SessionDiffer session loading from NDJSON files."""

    def test_load_session_from_ndjson(self):
        """SessionDiffer loads action_log.ndjson correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            session_dir = tmppath / ".cua" / "sessions" / "test-session"
            session_dir.mkdir(parents=True)

            # Write test action_log.ndjson
            action_log = session_dir / "action_log.ndjson"
            with open(action_log, "w") as f:
                f.write(json.dumps({"app": "Mail", "target_label": "Send", "action_type": "click"}) + "\n")
                f.write(json.dumps({"app": "Mail", "target_label": "To", "action_type": "type"}) + "\n")

            # Patch Path.home() to return tmppath
            import unittest.mock

            with unittest.mock.patch("pathlib.Path.home", return_value=tmppath):
                differ = SessionDiffer("test-session", "test-session")
                assert len(differ.session_a) == 2
                assert differ.session_a[0]["app"] == "Mail"

    def test_load_session_missing_file(self):
        """SessionDiffer returns empty list for missing action_log.ndjson."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            import unittest.mock

            with unittest.mock.patch("pathlib.Path.home", return_value=tmppath):
                differ = SessionDiffer("nonexistent", "nonexistent")
                assert differ.session_a == []
                assert differ.session_b == []
