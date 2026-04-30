"""Unit tests for L3Stub + L3Contract Protocol.

Per VERIFY-07: L3 LLM contract is a Pydantic-typed Protocol; L3Stub
raises ``NotImplementedError`` when invoked in Phase 1.

Phase 1 invariant: ANY L3 escalation in Phase 1 = bug. The Calculator
demo (Plan 09) MUST NOT reach L3 — L0+L1 alone produce confidence >=
0.50, so L2 escalation never fires either, and L3 is unreachable. If
L3Stub.verify is invoked, the aggregator catches NotImplementedError
and emits a structured 'l3.unavailable_phase1' warning event (Task 3).
"""
from __future__ import annotations

import time

import pytest

from cua_overlay.state.causal_dag import HoarePost
from cua_overlay.verifier.ensemble.l3_llm import L3Contract, L3Stub


# ----------------------------------------------------------------- Test 1


@pytest.mark.asyncio
async def test_stub_raises() -> None:
    """L3Stub.verify with proper-shaped args raises NotImplementedError."""
    hp = HoarePost(
        target_key="bbox:com.apple.Calculator:AXButton:120:220",
        confidence=0.20,
        tier_signals={"L0": 0.0, "L1": 0.0, "L2": None, "L3": None},
        verified=False,
        healed_to=None,
        timestamp_ns=time.monotonic_ns(),
    )
    stub = L3Stub()
    with pytest.raises(NotImplementedError) as exc_info:
        await stub.verify(screenshot=None, expected=hp, actual_signals={})

    # Phase 1 invariant: error message names "Phase 4" so callers know
    # this is intentional, not a forgotten implementation.
    assert "Phase 4" in str(exc_info.value)


# ----------------------------------------------------------------- Test 2


@pytest.mark.asyncio
async def test_stub_raises_with_any_args() -> None:
    """Catch-all signature: ANY positional/keyword combo still raises."""
    stub = L3Stub()
    # Variant A: positional args only
    with pytest.raises(NotImplementedError):
        await stub.verify("anything", "goes")
    # Variant B: kwargs only
    with pytest.raises(NotImplementedError):
        await stub.verify(here=42)
    # Variant C: empty args
    with pytest.raises(NotImplementedError):
        await stub.verify()


# ----------------------------------------------------------------- Test 3


def test_protocol_signature() -> None:
    """L3Contract is a runtime-checkable Protocol; L3Stub satisfies it."""
    # @runtime_checkable Protocol → isinstance check is structural.
    assert isinstance(L3Stub(), L3Contract), (
        "L3Stub must structurally satisfy the L3Contract Protocol "
        "so Phase 4 can drop in a real implementation without API drift"
    )
