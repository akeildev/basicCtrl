"""ACT-01 — ChannelRegistry registration + selection (D-14, D-30, T-2-06)."""
from __future__ import annotations

from typing import Literal, Optional

import anyio
import pytest

from basicctrl.actions.channel_registry import CHANNEL_TO_TIER_DEFAULT, ChannelRegistry, TIER_TO_CHANNEL_DEFAULT
from basicctrl.actions.channels.base import Channel, ChannelOutcome
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.actions.race_policy import RacePolicy
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.translators.base import TranslatorTarget


class _FakeChannel:
    def __init__(self, name: str) -> None:
        self.name = name  # type: ignore[assignment]

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        return ChannelOutcome(channel=self.name, status="fired")  # type: ignore[arg-type]


def test_register_and_get() -> None:
    reg = ChannelRegistry()
    c2 = _FakeChannel("C2")
    reg.register(c2)
    assert reg.get("C2") is c2
    assert reg.get("C9") is None


def test_select_race_returns_all_channels_for_priority() -> None:
    reg = ChannelRegistry()
    for n in ("C1", "C2", "C3", "C4", "C5"):
        reg.register(_FakeChannel(n))
    selected = reg.select(["T1", "T2", "T3", "T4", "T5"], RacePolicy.RACE)
    # T1→C2, T2→C5, T3→C4, T4→C1, T5→C3 — five distinct channels.
    assert [c.name for c in selected] == ["C2", "C5", "C4", "C1", "C3"]


def test_select_single_channel_stops_at_first() -> None:
    reg = ChannelRegistry()
    for n in ("C1", "C2", "C3", "C4", "C5"):
        reg.register(_FakeChannel(n))
    selected = reg.select(["T1", "T2", "T3"], RacePolicy.SINGLE_CHANNEL)
    assert len(selected) == 1
    assert selected[0].name == "C2"  # T1's default


def test_select_skips_unregistered_channels() -> None:
    reg = ChannelRegistry()
    reg.register(_FakeChannel("C2"))
    # T2's default C5 is NOT registered — skipped.
    selected = reg.select(["T2", "T1"], RacePolicy.RACE)
    assert [c.name for c in selected] == ["C2"]


def test_select_dedupes_channel_appearing_in_multiple_tiers() -> None:
    """If a channel covers multiple tiers (e.g. an alternate binding maps T4→C3
    AND T5→C3), select() de-dupes."""
    reg = ChannelRegistry()
    reg.register(_FakeChannel("C3"))

    # Force the T4 default to C3 to exercise dedupe.
    original_t4 = TIER_TO_CHANNEL_DEFAULT["T4"]
    try:
        TIER_TO_CHANNEL_DEFAULT["T4"] = "C3"
        selected = reg.select(["T4", "T5"], RacePolicy.RACE)
        assert [c.name for c in selected] == ["C3"]
    finally:
        TIER_TO_CHANNEL_DEFAULT["T4"] = original_t4


def test_channel_outcome_pydantic_rejects_bad_kind() -> None:
    """T-2-06 — Pydantic Literal rejects channel='C9'."""
    with pytest.raises(Exception):  # ValidationError
        ChannelOutcome(channel="C9", status="fired")  # type: ignore[arg-type]


def test_channel_outcome_is_frozen() -> None:
    """ChannelOutcome.model_config has frozen=True — mutation raises."""
    outcome = ChannelOutcome(channel="C2", status="fired", fired_at_ns=1)
    with pytest.raises(Exception):  # ValidationError on frozen mutation
        outcome.status = "errored"  # type: ignore[misc]


def test_channel_outcome_default_verified_false() -> None:
    """Channels never set verified=True; orchestrator does after verifier."""
    outcome = ChannelOutcome(channel="C2", status="fired")
    assert outcome.verified is False


def test_d14_default_binding_complete() -> None:
    """D-14 mapping: T1→C2, T2→C5, T3→C4, T4→C1, T5→C3."""
    assert TIER_TO_CHANNEL_DEFAULT == {
        "T1": "C2",
        "T2": "C5",
        "T3": "C4",
        "T4": "C1",
        "T5": "C3",
    }


def test_tier_for_channel_inverse_lookup() -> None:
    """tier_for_channel reverses the D-14 default mapping. Used by Plan 02-10
    RaceOrchestrator to fill ActionCanonical.tier from winner's ChannelOutcome.channel."""
    reg = ChannelRegistry()
    # No registration needed — tier_for_channel is a pure D-14 lookup.
    assert reg.tier_for_channel("C2") == "T1"
    assert reg.tier_for_channel("C5") == "T2"
    assert reg.tier_for_channel("C4") == "T3"
    assert reg.tier_for_channel("C1") == "T4"
    assert reg.tier_for_channel("C3") == "T5"
    # Unknown channel → None.
    assert reg.tier_for_channel("C99") is None
    assert reg.tier_for_channel("") is None


def test_channel_to_tier_default_is_inverse_of_tier_to_channel_default() -> None:
    """CHANNEL_TO_TIER_DEFAULT is the exact inverse of TIER_TO_CHANNEL_DEFAULT."""
    assert CHANNEL_TO_TIER_DEFAULT == {v: k for k, v in TIER_TO_CHANNEL_DEFAULT.items()}
    assert len(CHANNEL_TO_TIER_DEFAULT) == 5
