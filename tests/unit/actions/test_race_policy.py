"""ACT-04 — RacePolicy resolve dispatch (D-09..D-12, D-30, T-2-09)."""
from __future__ import annotations

import structlog
from structlog.testing import capture_logs

from cua_overlay.actions.race_policy import RacePolicy, resolve_race_policy


def test_auto_click_races() -> None:
    assert resolve_race_policy(RacePolicy.AUTO, "click") == RacePolicy.RACE


def test_auto_submit_single_channel() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "submit") == RacePolicy.SINGLE_CHANNEL
    )


def test_auto_send_single_channel() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "send") == RacePolicy.SINGLE_CHANNEL
    )


def test_auto_type_single_channel() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "type_into_focused")
        == RacePolicy.SINGLE_CHANNEL
    )


def test_auto_scroll_to_position_races() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "scroll_to_position")
        == RacePolicy.RACE
    )


def test_auto_scroll_by_delta_single_channel() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "scroll_by_delta")
        == RacePolicy.SINGLE_CHANNEL
    )


def test_auto_destructive_combo_single_channel() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "key_combo:cmd+s")
        == RacePolicy.SINGLE_CHANNEL
    )


def test_auto_safe_race_combo_cmd_c_races() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "key_combo:cmd+c") == RacePolicy.RACE
    )


def test_auto_safe_race_combo_cmd_v_races() -> None:
    assert (
        resolve_race_policy(RacePolicy.AUTO, "key_combo:cmd+v") == RacePolicy.RACE
    )


def test_explicit_single_channel_honored_for_click() -> None:
    assert (
        resolve_race_policy(RacePolicy.SINGLE_CHANNEL, "click")
        == RacePolicy.SINGLE_CHANNEL
    )


def test_race_request_for_destructive_blocked_with_warning() -> None:
    structlog.configure(processors=[structlog.testing.LogCapture()])
    with capture_logs() as cap:
        result = resolve_race_policy(RacePolicy.RACE, "submit")
    assert result == RacePolicy.SINGLE_CHANNEL
    assert any(
        e.get("event") == "race_policy.destructive_override_blocked" for e in cap
    )
