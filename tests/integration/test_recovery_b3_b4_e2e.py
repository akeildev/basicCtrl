"""B3/B4 real recovery branch wire-up — Phase 4 path verification.

Original (Phase B6): when ANTHROPIC_API_KEY is set, main.py constructs the
real B3RecoveryBranch + B4RecoveryBranch (not the stubs). The TestB3RealPath /
TestB4RealPath classes verify that wire-up via a mocked anthropic client.

J1 addition: TestB3SamplingPath / TestB4SamplingPath verify the same
end-to-end recovery flow when the planner is `MCPSamplingPlanner` driven by a
mocked FastMCP `Context` — i.e. the *no-API-key* path that lets Claude Code
service the LLM call via `sampling/createMessage`. These classes run
unconditionally when the gate env var is set, regardless of HAS_KEY.

To run a *real-API* version that hits Opus, set
`CUA_RUN_E2E_RECOVERY_REAL_LIVE=1` (additional env var). That variant
intentionally costs ~$0.05 per run.
"""
from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

GATE = os.environ.get("CUA_RUN_E2E_RECOVERY_REAL", "0") == "1"
LIVE = os.environ.get("CUA_RUN_E2E_RECOVERY_REAL_LIVE", "0") == "1"
HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

pytestmark = pytest.mark.skipif(
    not GATE,
    reason="set CUA_RUN_E2E_RECOVERY_REAL=1 to enable B3/B4 real-path test",
)


@pytest.fixture
def has_anthropic_key():
    if not HAS_KEY:
        pytest.skip("ANTHROPIC_API_KEY unset — B3/B4 real path requires it")


@pytest.fixture
def session_writer():
    sw = MagicMock()
    sw.append_action_log = MagicMock()
    return sw


@pytest.fixture
def idempotency_store():
    store = MagicMock()
    # try_claim returns a truthy claim object
    store.try_claim = AsyncMock(return_value={"action_id": "x", "channel": "y"})
    return store


@pytest.fixture
def fake_state_graph():
    sg = MagicMock()
    sg.app = "Calculator"
    sg.nodes = []
    return sg


@pytest.fixture
def fake_failure_ctx(fake_state_graph):
    """Synthesize a FailureCtx as B3/B4 would receive from RecoveryOrchestrator."""
    from basicctrl.state.causal_dag import ActionCanonical

    failed_action = ActionCanonical(
        id="act_test_1",
        step_idx=0,
        kind="MUTATE",
        target_key="btn_5",
        action_type="click",
        payload={},
        timestamp_ns=int(time.monotonic_ns()),
        session_id="test_session",
    )
    return {
        "bundle_id": "com.apple.calculator",
        "target_key": "btn_5",
        "action_id": "act_test_1",
        "action": failed_action,
        "state": fake_state_graph,
        "session_id": "test_session",
    }


@pytest.mark.integration
class TestB3RealPath:
    """B3RecoveryBranch with real Planner+WMP, mocked anthropic client."""

    @pytest.mark.asyncio
    async def test_b3_attempts_replan_via_world_model_and_planner(
        self, has_anthropic_key, session_writer, idempotency_store, fake_failure_ctx
    ):
        from basicctrl.cognition import Planner, WorldModelPredictor
        from basicctrl.recovery.branches import B3_WorldReplan

        planner = Planner()
        wmp = WorldModelPredictor()

        if not LIVE:
            # Mock the anthropic client so plan_action returns a canned PlanCandidate
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.content = [
                MagicMock(
                    text=json.dumps(
                        {
                            "steps": [
                                {
                                    "kind": "MUTATE",
                                    "target_key": "btn_5",
                                    "action_type": "click",
                                    "payload": {},
                                }
                            ],
                            "preconds": [],
                            "success_criteria": ["Calculator display reads 5"],
                        }
                    )
                )
            ]
            mock_client.messages.create.return_value = mock_resp
            planner.client = mock_client
            planner._client_initialized = True

        b3 = B3_WorldReplan(
            idempotency_store=idempotency_store,
            session_writer=session_writer,
            world_model_predictor=wmp,
            planner=planner,
        )

        # Attempt recovery
        outcome = await b3.attempt(fake_failure_ctx)

        # B3 returns a replanned ActionCanonical (not None) on success
        assert outcome is not None, (
            f"B3 should return a replanned action on success; got {outcome}"
        )

        # Branch attempt + success events emitted
        events = [c.args[0] for c in session_writer.append_action_log.call_args_list]
        kinds = [e.get("event") for e in events]
        assert "branch_attempt" in kinds
        assert "branch_success" in kinds, (
            f"expected branch_success, got events: {kinds}"
        )


@pytest.mark.integration
class TestB4RealPath:
    """B4RecoveryBranch with real Planner+Critic, mocked anthropic client."""

    @pytest.mark.asyncio
    async def test_b4_generates_candidates_and_critic_picks_winner(
        self, has_anthropic_key, session_writer, idempotency_store, fake_failure_ctx
    ):
        from basicctrl.cognition import Critic, Planner
        from basicctrl.recovery.branches import B4_PlannerRequery

        planner = Planner()
        critic = Critic()

        if not LIVE:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.content = [
                MagicMock(
                    text=json.dumps(
                        {
                            "steps": [
                                {
                                    "kind": "MUTATE",
                                    "target_key": "btn_5",
                                    "action_type": "click",
                                    "payload": {},
                                }
                            ],
                            "preconds": [],
                            "success_criteria": ["recovered"],
                        }
                    )
                )
            ]
            mock_client.messages.create.return_value = mock_resp
            planner.client = mock_client
            planner._client_initialized = True

        b4 = B4_PlannerRequery(
            idempotency_store=idempotency_store,
            session_writer=session_writer,
            planner=planner,
            critic=critic,
            num_candidates=2,  # keep it cheap
        )

        outcome = await b4.attempt(fake_failure_ctx)

        assert outcome is not None
        events = [c.args[0] for c in session_writer.append_action_log.call_args_list]
        kinds = [e.get("event") for e in events]
        assert "branch_attempt" in kinds
        assert "branch_success" in kinds


# ---------------------------------------------------------------------------
# J1 — Sampling-mode path (no ANTHROPIC_API_KEY required)
# ---------------------------------------------------------------------------


def _sampling_ctx_returning(json_payload: str) -> MagicMock:
    """Build a fake FastMCP Context whose session.create_message returns
    a CreateMessageResult-like object with .content.text == json_payload."""
    ctx = MagicMock()
    ctx.session.check_client_capability = MagicMock(return_value=True)
    ctx.session.create_message = AsyncMock(
        return_value=MagicMock(content=MagicMock(text=json_payload))
    )
    return ctx


def _planner_factory_using_ctx():
    """Mirror main.py's _planner_factory but skip the SDK Planner branch
    so the test exercises ONLY the sampling path."""
    from basicctrl.cognition import MCPSamplingPlanner

    def factory(ctx):
        if ctx is not None and MCPSamplingPlanner.host_supports_sampling(ctx):
            return MCPSamplingPlanner(ctx)
        return None

    return factory


@pytest.mark.integration
class TestB3SamplingPath:
    """B3 with MCPSamplingPlanner — proves J1 wire-up holds without a key."""

    @pytest.mark.asyncio
    async def test_b3_replans_via_sampling_when_host_supports_it(
        self, session_writer, idempotency_store, fake_failure_ctx
    ):
        from basicctrl.cognition import WorldModelPredictor
        from basicctrl.recovery.branches import B3_WorldReplan

        wmp = WorldModelPredictor()  # heuristic, no key

        ctx = _sampling_ctx_returning(
            json.dumps(
                {
                    "steps": [
                        {
                            "kind": "MUTATE",
                            "target_key": "btn_5",
                            "action_type": "click",
                            "payload": {},
                        }
                    ],
                    "preconds": [],
                    "success_criteria": ["sampled recovery"],
                }
            )
        )
        fake_failure_ctx["ctx"] = ctx

        b3 = B3_WorldReplan(
            idempotency_store=idempotency_store,
            session_writer=session_writer,
            world_model_predictor=wmp,
            planner_factory=_planner_factory_using_ctx(),
        )

        outcome = await b3.attempt(fake_failure_ctx)
        assert outcome is not None, "B3 should produce a replan via sampling"
        ctx.session.create_message.assert_awaited()  # the host saw the request

        events = [c.args[0] for c in session_writer.append_action_log.call_args_list]
        kinds = [e.get("event") for e in events]
        assert "branch_attempt" in kinds
        assert "branch_success" in kinds

    @pytest.mark.asyncio
    async def test_b3_emits_no_planner_available_when_host_lacks_sampling(
        self, session_writer, idempotency_store, fake_failure_ctx
    ):
        from basicctrl.cognition import WorldModelPredictor
        from basicctrl.recovery.branches import B3_WorldReplan

        wmp = WorldModelPredictor()

        ctx = MagicMock()
        ctx.session.check_client_capability = MagicMock(return_value=False)
        fake_failure_ctx["ctx"] = ctx

        b3 = B3_WorldReplan(
            idempotency_store=idempotency_store,
            session_writer=session_writer,
            world_model_predictor=wmp,
            planner_factory=_planner_factory_using_ctx(),
        )

        outcome = await b3.attempt(fake_failure_ctx)
        assert outcome is None

        events = [c.args[0] for c in session_writer.append_action_log.call_args_list]
        reasons = [e.get("reason") for e in events if e.get("event") == "branch_failed"]
        assert "no_planner_available" in reasons


@pytest.mark.integration
class TestB4SamplingPath:
    """B4 with MCPSamplingPlanner — proves J1 wire-up holds without a key."""

    @pytest.mark.asyncio
    async def test_b4_ranks_sampling_candidates(
        self, session_writer, idempotency_store, fake_failure_ctx
    ):
        from basicctrl.cognition import Critic
        from basicctrl.recovery.branches import B4_PlannerRequery

        critic = Critic()

        ctx = _sampling_ctx_returning(
            json.dumps(
                {
                    "steps": [
                        {
                            "kind": "MUTATE",
                            "target_key": "btn_5",
                            "action_type": "click",
                            "payload": {},
                        }
                    ],
                    "preconds": [],
                    "success_criteria": ["sampled recovery"],
                }
            )
        )
        fake_failure_ctx["ctx"] = ctx

        b4 = B4_PlannerRequery(
            idempotency_store=idempotency_store,
            session_writer=session_writer,
            critic=critic,
            planner_factory=_planner_factory_using_ctx(),
            num_candidates=2,
        )

        outcome = await b4.attempt(fake_failure_ctx)
        assert outcome is not None
        # B4 calls planner.plan_action `num_candidates` times → ≥2 sampling roundtrips
        assert ctx.session.create_message.await_count >= 2

        events = [c.args[0] for c in session_writer.append_action_log.call_args_list]
        kinds = [e.get("event") for e in events]
        assert "branch_attempt" in kinds
        assert "branch_success" in kinds
