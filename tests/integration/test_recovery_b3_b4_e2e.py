"""B3/B4 real recovery branch wire-up — Phase 4 path verification.

Per ULTRAPLAN Phase B6: when ANTHROPIC_API_KEY is set, main.py constructs
the real B3RecoveryBranch + B4RecoveryBranch (not the stubs). This test
verifies the wire-up holds end-to-end through one branch attempt cycle.

Approach (cost-conscious): use a real Planner/WMP/Critic constructor (so the
ANTHROPIC_API_KEY validation runs), but mock the anthropic.Anthropic client
so no real API calls are made — burns no tokens.

To run a *real-API* version that hits Opus, set
`CUA_RUN_E2E_RECOVERY_REAL_LIVE=1` (additional env var). That variant
intentionally costs ~$0.05 per run.

Both variants skip cleanly when the env var or key is unset.
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
    from cua_overlay.state.causal_dag import ActionCanonical

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
        from cua_overlay.cognition import Planner, WorldModelPredictor
        from cua_overlay.recovery.branches import B3_WorldReplan

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
        from cua_overlay.cognition import Critic, Planner
        from cua_overlay.recovery.branches import B4_PlannerRequery

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
