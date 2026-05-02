"""MCP-02 Phase 2 — 6 healing tool schemas + T-2-09 server-override tests.

Replaces the Wave-0 stub. Validates D-28..D-31 contracts:
  - 6 tools registered (D-29)
  - send_destructive has NO race_policy (D-29 safety-by-name)
  - Pydantic Literal['auto','race','single_channel'] race_policy enum (D-30)
  - Server-side T-2-09 mitigation via SAFE_RACE_COMBOS + always-SINGLE_CHANNEL
    for send_destructive

Per VALIDATION.md per-task verification map row 02-10-01.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# Tools registered onto a FastMCP proxy are accessed via the proxy's tool
# registry. To unit-test the tool callables directly we extract them from
# register_healing_tools — done via a fake FastMCP that captures decorator
# applications.


class _FakeFastMCP:
    """Minimal FastMCP test double that captures @proxy.tool decorations."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str = "", description: str = "", **kwargs: Any) -> Any:
        def _decorator(fn: Any) -> Any:
            self.tools[name] = fn
            return fn
        return _decorator


@pytest.fixture
def fake_proxy_with_tools():
    """Spin up the 6 Phase 2 tools against a fake FastMCP + mocked RaceOrchestrator."""
    from cua_overlay.actions.race_policy import RacePolicy
    from cua_overlay.mcp_server.healing_tools import register_healing_tools
    from cua_overlay.state.causal_dag import ActionCanonical, HoarePost

    proxy = _FakeFastMCP()
    upstream = MagicMock()

    fake_session = MagicMock()
    fake_session.session_id = "test-session-id"
    deps = MagicMock()
    deps.session = fake_session

    # Mock race orchestrator that returns a deterministic (action, post) tuple
    # AND records the policy + action_type it was called with.
    fake_action = ActionCanonical(
        id="action-id-1",
        step_idx=0,
        kind="MUTATE",
        target_key="axid:test:button",
        action_type="click",
        payload={},
        tier="T1",
        channel="C2",
        timestamp_ns=1000,
        session_id="test-session-id",
    )
    fake_post = HoarePost(
        target_key="axid:test:button",
        confidence=0.95,
        tier_signals={"L0": 1.0, "L1": 1.0, "L2": None, "L3": None},
        verified=True,
        healed_to=None,
        timestamp_ns=2000,
    )

    race_orch = MagicMock()
    race_orch.execute = AsyncMock(return_value=(fake_action, fake_post))

    # Drive the registration. register_healing_tools is async; pump it through
    # an event loop manually because it's purely metadata-binding (no awaits
    # over IO).
    import asyncio
    asyncio.run(register_healing_tools(proxy, upstream, deps, race_orch))

    return SimpleNamespace(
        proxy=proxy,
        deps=deps,
        race_orch=race_orch,
        RacePolicy=RacePolicy,
    )


def test_six_tools_registered(fake_proxy_with_tools) -> None:
    """D-29: 6 healing tools registered. Memory loop adds register_task_complete
    (J1+ memory wire) so the registered set is now 7 by default."""
    expected = {
        "click_with_healing",
        "type_with_healing",
        "scroll_with_healing",
        "set_value_with_healing",
        "send_destructive",
        "key_combo_with_healing",
        "register_task_complete",
    }
    assert set(fake_proxy_with_tools.proxy.tools.keys()) == expected


def test_click_with_healing_signature_phase1_compat(fake_proxy_with_tools) -> None:
    """Phase 1 callers passing only (x, y, bundle_id, pid, label) still work."""
    fn = fake_proxy_with_tools.proxy.tools["click_with_healing"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    # First 5 args must be Phase 1's order.
    assert params[:5] == ["x", "y", "bundle_id", "pid", "label"]
    # Phase 2 args appended.
    assert "race_policy" in params
    assert "prefer_tier" in params
    assert "prefer_channel" in params


def test_type_with_healing_signature(fake_proxy_with_tools) -> None:
    fn = fake_proxy_with_tools.proxy.tools["type_with_healing"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "text" in params
    assert "bundle_id" in params
    assert "pid" in params
    assert "target_label" in params
    assert "race_policy" in params


def test_scroll_with_healing_signature(fake_proxy_with_tools) -> None:
    fn = fake_proxy_with_tools.proxy.tools["scroll_with_healing"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "direction" in params
    assert "amount" in params
    assert "bundle_id" in params
    assert "pid" in params
    assert "action_kind" in params
    assert "race_policy" in params


def test_set_value_with_healing_signature(fake_proxy_with_tools) -> None:
    fn = fake_proxy_with_tools.proxy.tools["set_value_with_healing"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "target_label" in params
    assert "value" in params
    assert "bundle_id" in params
    assert "pid" in params
    assert "race_policy" in params


def test_send_destructive_has_no_race_policy_param(fake_proxy_with_tools) -> None:
    """D-29: send_destructive encodes safety in tool name; NO race_policy."""
    fn = fake_proxy_with_tools.proxy.tools["send_destructive"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "race_policy" not in params, (
        f"send_destructive must not expose race_policy (D-29); got params={params}"
    )
    # confirmation_phrase should be present (Open Question 4 in RESEARCH).
    assert "confirmation_phrase" in params


def test_key_combo_with_healing_signature(fake_proxy_with_tools) -> None:
    fn = fake_proxy_with_tools.proxy.tools["key_combo_with_healing"]
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "combo" in params
    assert "bundle_id" in params
    assert "pid" in params
    assert "race_policy" in params


@pytest.mark.asyncio
async def test_click_with_healing_passes_race_policy_through(fake_proxy_with_tools) -> None:
    """T-2-09 layer 2: race_policy='race' for click is forwarded as RACE to orchestrator."""
    fo = fake_proxy_with_tools
    fn = fo.proxy.tools["click_with_healing"]
    await fn(x=10, y=20, bundle_id="com.test", pid=1, label="btn", race_policy="race")
    fo.race_orch.execute.assert_awaited_once()
    call_kwargs = fo.race_orch.execute.await_args.kwargs
    assert call_kwargs["race_policy"] == fo.RacePolicy.RACE
    assert call_kwargs["action_type"] == "click"


@pytest.mark.asyncio
async def test_set_value_caller_passes_race_still_forwarded_to_orchestrator(
    fake_proxy_with_tools,
) -> None:
    """T-2-09 layer 3: caller-forced 'race' for set_value is FORWARDED to orchestrator;
    the SINGLE_CHANNEL override happens INSIDE resolve_race_policy (Plan 02-10), not at MCP layer.
    MCP layer's job is forward + log; orchestrator owns the override."""
    fo = fake_proxy_with_tools
    fn = fo.proxy.tools["set_value_with_healing"]
    await fn(
        target_label="email",
        value="x@y",
        bundle_id="com.test",
        pid=1,
        race_policy="race",
    )
    call_kwargs = fo.race_orch.execute.await_args.kwargs
    # MCP forwards faithfully — orchestrator overrides via resolve_race_policy.
    assert call_kwargs["race_policy"] == fo.RacePolicy.RACE
    assert call_kwargs["action_type"] == "set_value"


@pytest.mark.asyncio
async def test_send_destructive_always_single_channel(fake_proxy_with_tools) -> None:
    """T-2-09 layer 1: send_destructive ALWAYS passes SINGLE_CHANNEL regardless of any input."""
    fo = fake_proxy_with_tools
    fn = fo.proxy.tools["send_destructive"]
    await fn(target_label="Send", bundle_id="com.test", pid=1)
    call_kwargs = fo.race_orch.execute.await_args.kwargs
    assert call_kwargs["race_policy"] == fo.RacePolicy.SINGLE_CHANNEL
    assert call_kwargs["action_type"] == "submit"


@pytest.mark.asyncio
async def test_key_combo_safe_race_combos_use_prefix_action_type(
    fake_proxy_with_tools,
) -> None:
    """D-12: cmd+c, cmd+v dispatch as action_type='key_combo:<combo>' so the
    race_policy `key_combo:` prefix handler routes to RACE via SAFE_RACE_COMBOS."""
    fo = fake_proxy_with_tools
    fn = fo.proxy.tools["key_combo_with_healing"]
    for combo in ["cmd+c", "cmd+v"]:
        fo.race_orch.execute.reset_mock()
        await fn(combo=combo, bundle_id="com.test", pid=1)
        call_kwargs = fo.race_orch.execute.await_args.kwargs
        assert call_kwargs["action_type"] == f"key_combo:{combo}", (
            f"combo={combo} did not dispatch as key_combo:{combo}"
        )


@pytest.mark.asyncio
async def test_key_combo_destructive_uses_prefix_action_type(
    fake_proxy_with_tools,
) -> None:
    """D-11: cmd+s, cmd+enter, cmd+w, cmd+z dispatch as 'key_combo:<combo>' too;
    the race_policy prefix handler routes them to SINGLE_CHANNEL via DESTRUCTIVE_COMBOS."""
    fo = fake_proxy_with_tools
    fn = fo.proxy.tools["key_combo_with_healing"]
    for combo in ["cmd+s", "cmd+enter", "cmd+w", "cmd+z"]:
        fo.race_orch.execute.reset_mock()
        await fn(combo=combo, bundle_id="com.test", pid=1)
        call_kwargs = fo.race_orch.execute.await_args.kwargs
        assert call_kwargs["action_type"] == f"key_combo:{combo}", (
            f"combo={combo} did not dispatch as key_combo:{combo}"
        )


@pytest.mark.asyncio
async def test_all_tools_return_phase2_result_shape(fake_proxy_with_tools) -> None:
    """All 6 tools return dict with phase=2, verified, confidence, race fields."""
    fo = fake_proxy_with_tools

    # Use minimal valid kwargs per tool.
    invocations = [
        ("click_with_healing", dict(x=10, y=20)),
        ("type_with_healing", dict(text="hi", bundle_id="com.test", pid=1)),
        ("scroll_with_healing", dict(direction="down", amount=100, bundle_id="com.test", pid=1)),
        ("set_value_with_healing", dict(target_label="x", value="v", bundle_id="com.test", pid=1)),
        ("send_destructive", dict(target_label="Send", bundle_id="com.test", pid=1)),
        ("key_combo_with_healing", dict(combo="cmd+c", bundle_id="com.test", pid=1)),
    ]
    for tool_name, kwargs in invocations:
        fn = fo.proxy.tools[tool_name]
        result = await fn(**kwargs)
        assert isinstance(result, dict), f"{tool_name} did not return dict"
        assert result["phase"] == 2, f"{tool_name} phase != 2"
        assert "verified" in result
        assert "confidence" in result
        assert "race" in result
        assert "tier_won" in result["race"]
        assert "channel_won" in result["race"]
        assert "latency_ms" in result["race"]
        assert "verifier_confidence" in result["race"]
        assert "near_miss_duplicate_count" in result["race"]
        assert result["session_id"] == "test-session-id"


# ----------------------------- F10 — recovery wiring -------------------------


async def _build_proxy_with_recovery(verified: bool):
    """Async helper — spin up healing tools with a configurable verified flag
    and a mocked RecoveryOrchestrator. Async so it can be awaited from inside
    pytest-asyncio's event loop (asyncio.run() can't be called there)."""
    from cua_overlay.actions.race_policy import RacePolicy
    from cua_overlay.actions.channels.base import ChannelOutcome
    from cua_overlay.mcp_server.healing_tools import register_healing_tools
    from cua_overlay.state.causal_dag import ActionCanonical, HoarePost

    proxy = _FakeFastMCP()
    upstream = MagicMock()
    deps = MagicMock()
    deps.session = MagicMock(session_id="test-session-id")

    fake_action = ActionCanonical(
        id="action-id-recovery", step_idx=0, kind="MUTATE",
        target_key="axid:test:button", action_type="click", payload={},
        tier="T1", channel="C2", timestamp_ns=1000,
        session_id="test-session-id",
    )
    fake_post = HoarePost(
        target_key="axid:test:button",
        confidence=1.0 if verified else 0.0,
        tier_signals={"L0": 1.0 if verified else 0.0, "L1": 0.0,
                       "L2": None, "L3": None},
        verified=verified, healed_to=None, timestamp_ns=2000,
    )
    race_orch = MagicMock()
    race_orch.execute = AsyncMock(return_value=(fake_action, fake_post))

    recovered_outcome = ChannelOutcome(
        channel="C4", status="fired", verified=True, fired_at_ns=3000,
    )
    recovery_log = [
        {"event": "recovery.classified", "action_id": "action-id-recovery"},
        {"event": "branch_attempt", "branch": "B1_RESCROLL"},
        {"event": "branch_attempt", "branch": "B2_OCR_REGROUNDING"},
        {"event": "recovery_succeeded", "winner": "B1_RESCROLL"},
    ]
    recovery_orch = MagicMock()
    recovery_orch.attempt = AsyncMock(return_value=(recovered_outcome, recovery_log))

    await register_healing_tools(proxy, upstream, deps, race_orch, recovery_orch)

    return SimpleNamespace(
        proxy=proxy, race_orch=race_orch, recovery_orch=recovery_orch,
        action=fake_action, post=fake_post,
    )


@pytest.mark.asyncio
async def test_click_invokes_recovery_when_verified_false() -> None:
    """F10: when race_orch returns verified=False, click_with_healing must
    call recovery_orch.attempt(...) and surface the outcome in the response."""
    fo = await _build_proxy_with_recovery(verified=False)
    fn = fo.proxy.tools["click_with_healing"]
    result = await fn(x=10, y=20, bundle_id="com.test", pid=1, label="btn")

    fo.recovery_orch.attempt.assert_awaited_once()
    ctx = fo.recovery_orch.attempt.await_args.args[0]
    assert ctx["bundle_id"] == "com.test"
    assert ctx["target_key"] == "axid:test:button"
    assert ctx["confidence"] == 0.0
    assert ctx["action_type"] == "click"
    assert ctx["action_id"] == "action-id-recovery"

    assert result["recovery"]["ran"] is True
    assert result["recovery"]["succeeded"] is True
    assert "B1_RESCROLL" in result["recovery"]["branches_attempted"]
    assert result["recovery"]["terminal_event"] == "recovery_succeeded"


@pytest.mark.asyncio
async def test_click_skips_recovery_when_verified_true() -> None:
    """F10: when race_orch returns verified=True, recovery is NOT invoked."""
    fo = await _build_proxy_with_recovery(verified=True)
    fn = fo.proxy.tools["click_with_healing"]
    result = await fn(x=10, y=20, bundle_id="com.test", pid=1, label="btn")

    fo.recovery_orch.attempt.assert_not_awaited()
    assert result["recovery"]["ran"] is False


@pytest.mark.asyncio
async def test_send_destructive_skips_recovery_even_when_verified_false() -> None:
    """F10 + D-11 safety: destructive verbs never trigger automatic recovery
    branches (which include AppleScript fallback that could double-fire the
    destructive action)."""
    fo = await _build_proxy_with_recovery(verified=False)
    fn = fo.proxy.tools["send_destructive"]
    result = await fn(target_label="Send", bundle_id="com.test", pid=1)
    fo.recovery_orch.attempt.assert_not_awaited()
    # send_destructive doesn't expose a 'recovery' key — it just returns the
    # raw verified=False outcome.
    assert "recovery" not in result or result.get("recovery", {}).get("ran") is False
