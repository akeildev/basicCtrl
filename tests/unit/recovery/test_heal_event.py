"""Tests for heal event model.

Covers schema validation, frozen constraint, is_stable_tier routing,
and serialization.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from cua_overlay.recovery.heal_event import HealEvent


def test_heal_event_creation_valid() -> None:
    """Test creating a valid HealEvent with all fields."""
    now = datetime.utcnow()
    event = HealEvent(
        old_locator="old_sel",
        new_locator="new_sel",
        reason="test heal",
        trace_id="trace123",
        ts=now,
        locator_tier="AXLabel",
        source_branch="B1_RESCROLL",
    )
    assert event.old_locator == "old_sel"
    assert event.new_locator == "new_sel"
    assert event.reason == "test heal"
    assert event.trace_id == "trace123"
    assert event.ts == now
    assert event.locator_tier == "AXLabel"
    assert event.source_branch == "B1_RESCROLL"


def test_heal_event_frozen() -> None:
    """Test that HealEvent is frozen (immutable)."""
    event = HealEvent(
        old_locator="old_sel",
        new_locator="new_sel",
        reason="test",
        trace_id="trace123",
        locator_tier="AXLabel",
        source_branch="B1",
    )
    with pytest.raises(ValidationError):
        event.old_locator = "modified"  # type: ignore


def test_is_stable_tier_true_for_ax_identifier() -> None:
    """Test is_stable_tier returns True for AXIdentifier."""
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="AXIdentifier",
        source_branch="B1",
    )
    assert event.is_stable_tier() is True


def test_is_stable_tier_true_for_ax_label() -> None:
    """Test is_stable_tier returns True for AXLabel."""
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="AXLabel",
        source_branch="B1",
    )
    assert event.is_stable_tier() is True


def test_is_stable_tier_true_for_ax_title() -> None:
    """Test is_stable_tier returns True for AXTitle."""
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="AXTitle",
        source_branch="B1",
    )
    assert event.is_stable_tier() is True


def test_is_stable_tier_true_for_ax_role_description() -> None:
    """Test is_stable_tier returns True for AXRoleDescription."""
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="AXRoleDescription",
        source_branch="B1",
    )
    assert event.is_stable_tier() is True


def test_is_stable_tier_false_for_vision() -> None:
    """Test is_stable_tier returns False for Vision."""
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="Vision",
        source_branch="B2",
    )
    assert event.is_stable_tier() is False


def test_is_stable_tier_false_for_coordinate() -> None:
    """Test is_stable_tier returns False for Coordinate."""
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="Coordinate",
        source_branch="B5",
    )
    assert event.is_stable_tier() is False


def test_heal_event_invalid_tier() -> None:
    """Test that invalid locator_tier raises ValidationError."""
    with pytest.raises(ValidationError):
        HealEvent(
            old_locator="old",
            new_locator="new",
            reason="test",
            trace_id="trace",
            locator_tier="InvalidTier",  # type: ignore
            source_branch="B1",
        )


def test_serialize_for_ndjson() -> None:
    """Test serialization to NDJSON format."""
    now = datetime.utcnow()
    event = HealEvent(
        old_locator="old_sel",
        new_locator="new_sel",
        reason="test heal",
        trace_id="trace123",
        ts=now,
        locator_tier="AXLabel",
        source_branch="B1_RESCROLL",
    )
    serialized = event.serialize_for_ndjson()
    assert isinstance(serialized, dict)
    assert serialized["old_locator"] == "old_sel"
    assert serialized["new_locator"] == "new_sel"
    assert serialized["reason"] == "test heal"
    assert serialized["trace_id"] == "trace123"
    assert serialized["ts"] == now.isoformat()
    assert serialized["locator_tier"] == "AXLabel"
    assert serialized["source_branch"] == "B1_RESCROLL"


def test_heal_event_ts_auto_now() -> None:
    """Test that ts defaults to current time if omitted."""
    before = datetime.utcnow()
    event = HealEvent(
        old_locator="old",
        new_locator="new",
        reason="test",
        trace_id="trace",
        locator_tier="AXLabel",
        source_branch="B1",
    )
    after = datetime.utcnow()
    assert before <= event.ts <= after
