"""Unit tests for MCPSamplingPlanner (J1).

J1 goal: B3/B4 perform LLM calls via MCP `sampling/createMessage` so the
host (Claude Code etc.) services them — no `ANTHROPIC_API_KEY` needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("basicctrl.cognition.sampling_planner")

from basicctrl.cognition.exceptions import CognitionDisabledError
from basicctrl.cognition.sampling_planner import MCPSamplingPlanner


def _ctx_with_sampling(supported: bool) -> MagicMock:
    """Build a fake FastMCP Context whose session.check_client_capability
    returns the requested verdict."""
    ctx = MagicMock()
    ctx.session.check_client_capability = MagicMock(return_value=supported)
    return ctx


@pytest.mark.unit
class TestHostSupportsSampling:
    def test_returns_true_when_host_advertises_sampling(self):
        ctx = _ctx_with_sampling(True)
        assert MCPSamplingPlanner.host_supports_sampling(ctx) is True

    def test_returns_false_when_host_lacks_sampling(self):
        ctx = _ctx_with_sampling(False)
        assert MCPSamplingPlanner.host_supports_sampling(ctx) is False

    def test_returns_false_on_probe_exception(self):
        ctx = MagicMock()
        ctx.session.check_client_capability = MagicMock(
            side_effect=RuntimeError("session not ready")
        )
        assert MCPSamplingPlanner.host_supports_sampling(ctx) is False


@pytest.mark.unit
class TestPlanAction:
    @pytest.mark.asyncio
    async def test_calls_create_message_and_parses_steps(self):
        ctx = _ctx_with_sampling(True)
        ctx.session.create_message = AsyncMock(
            return_value=MagicMock(
                content=MagicMock(
                    text='{"steps":[{"kind":"MUTATE","action_type":"click"}],'
                    '"preconds":[],"success_criteria":["clicked"]}'
                )
            )
        )

        planner = MCPSamplingPlanner(ctx)
        state = MagicMock(app="TextEdit", nodes=[])
        plan = await planner.plan_action("test task", state)

        assert plan.steps == [{"kind": "MUTATE", "action_type": "click"}]
        assert plan.success_criteria == ["clicked"]
        assert plan.bounded is True
        ctx.session.create_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_cognition_disabled_on_host_error(self):
        ctx = _ctx_with_sampling(True)
        ctx.session.create_message = AsyncMock(
            side_effect=RuntimeError("transport closed")
        )

        planner = MCPSamplingPlanner(ctx)
        with pytest.raises(CognitionDisabledError) as excinfo:
            await planner.plan_action("test", MagicMock(app="X", nodes=[]))
        assert "transport closed" in excinfo.value.reason

    @pytest.mark.asyncio
    async def test_returns_empty_plan_on_unparseable_response(self):
        ctx = _ctx_with_sampling(True)
        ctx.session.create_message = AsyncMock(
            return_value=MagicMock(
                content=MagicMock(text="not json at all, sorry")
            )
        )

        planner = MCPSamplingPlanner(ctx)
        plan = await planner.plan_action("test", MagicMock(app="X", nodes=[]))
        assert plan.steps == []
        assert plan.bounded is True

    @pytest.mark.asyncio
    async def test_extracts_json_from_markdown_fence(self):
        ctx = _ctx_with_sampling(True)
        ctx.session.create_message = AsyncMock(
            return_value=MagicMock(
                content=MagicMock(
                    text='```json\n{"steps":[{"kind":"READ"}],"preconds":[],'
                    '"success_criteria":["s"]}\n```'
                )
            )
        )

        planner = MCPSamplingPlanner(ctx)
        plan = await planner.plan_action("test", MagicMock(app="X", nodes=[]))
        assert plan.steps == [{"kind": "READ"}]

    @pytest.mark.asyncio
    async def test_skill_markdown_threaded_into_user_message(self):
        """α3: per-app skill markdown is concatenated into the planner
        prompt so the LLM has prior knowledge about the app."""
        ctx = _ctx_with_sampling(True)
        captured: dict = {}

        async def fake_create_message(messages, **kwargs):
            captured["messages"] = messages
            return MagicMock(
                content=MagicMock(
                    text='{"steps":[],"preconds":[],"success_criteria":[]}'
                )
            )

        ctx.session.create_message = AsyncMock(side_effect=fake_create_message)

        planner = MCPSamplingPlanner(ctx)
        # com.apple.calculator has a skill file in basicctrl/skills/.
        state = MagicMock(app="com.apple.calculator", nodes=[])
        await planner.plan_action("compute 17 times 23", state)
        text = captured["messages"][0].content.text
        assert "App skill notes for com.apple.calculator" in text, text[:300]

    @pytest.mark.asyncio
    async def test_skill_block_omitted_when_no_skills_filed(self):
        ctx = _ctx_with_sampling(True)
        captured: dict = {}

        async def fake_create_message(messages, **kwargs):
            captured["messages"] = messages
            return MagicMock(
                content=MagicMock(
                    text='{"steps":[],"preconds":[],"success_criteria":[]}'
                )
            )

        ctx.session.create_message = AsyncMock(side_effect=fake_create_message)
        planner = MCPSamplingPlanner(ctx)
        state = MagicMock(app="com.example.never-heard-of", nodes=[])
        await planner.plan_action("test", state)
        text = captured["messages"][0].content.text
        assert "App skill notes" not in text

    @pytest.mark.asyncio
    async def test_truncates_to_max_steps(self):
        ctx = _ctx_with_sampling(True)
        # 25 steps, max_steps=20 → should truncate
        big_steps = [{"kind": "READ", "step_idx": i} for i in range(25)]
        import json as _json

        ctx.session.create_message = AsyncMock(
            return_value=MagicMock(
                content=MagicMock(
                    text=_json.dumps(
                        {"steps": big_steps, "preconds": [], "success_criteria": []}
                    )
                )
            )
        )

        planner = MCPSamplingPlanner(ctx, max_steps=20)
        plan = await planner.plan_action("test", MagicMock(app="X", nodes=[]))
        assert len(plan.steps) == 20
