"""Pytest fixtures for cache tests.

Provides:
  - session_dir: temporary directory for test session
  - agent_cache: AgentCache instance pointing to session_dir
  - sample_cassette_step: CassetteStep with mock Hoare objects
  - sample_cassette: Cassette with 3 sample steps
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator
from uuid import uuid4

import pytest

from cua_overlay.cache.agent_cache import AgentCache
from cua_overlay.cache.cassette import Cassette, CassetteStep
from cua_overlay.cache.key import compute_cache_key
from cua_overlay.state.causal_dag import ActionCanonical, HoarePost, HoarePre


@pytest.fixture
def session_dir() -> Generator[Path, None, None]:
    """Create a temporary session directory for the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def agent_cache(session_dir: Path) -> AgentCache:
    """Create an AgentCache instance for the test."""
    return AgentCache(session_dir)


@pytest.fixture
def sample_cassette_step() -> CassetteStep:
    """Create a sample CassetteStep with mock Hoare objects."""
    hoare_pre = HoarePre(
        target_key="button-submit",
        target_exists=True,
        target_enabled=True,
        target_role="AXButton",
        role_compatible=True,
        frontmost_app="com.apple.calculator",
        no_blocking_modal=True,
        timestamp_ns=1000000,
    )

    action_canonical = ActionCanonical(
        id=str(uuid4()),
        step_idx=0,
        kind="MUTATE",
        target_key="button-submit",
        action_type="click",
        payload={"x": 100, "y": 200},
        tier="T1",
        channel="C2",
        timestamp_ns=1000001,
        session_id="test-session",
    )

    hoare_post = HoarePost(
        target_key="button-submit",
        confidence=0.95,
        tier_signals={"L0": 0.95, "L1": None, "L2": None, "L3": None},
        verified=True,
        timestamp_ns=1000002,
    )

    return CassetteStep(
        step_idx=0,
        hoare_pre=hoare_pre,
        action_canonical=action_canonical,
        hoare_post=hoare_post,
        screenshot_phash="abc123def4560000000000000000000000000000000000000000000000000000",
        ax_subtree_hash="hash1",
        healed_selectors=[],
    )


@pytest.fixture
def sample_cassette(sample_cassette_step: CassetteStep) -> Cassette:
    """Create a sample Cassette with 3 steps."""
    bundle_id = "com.apple.calculator"
    role_path = "AXApplication > AXWindow > AXButton"
    instruction = "click the equals button three times"
    cache_key = compute_cache_key(bundle_id, role_path, instruction)

    cassette = Cassette(
        cache_key=cache_key,
        bundle_id=bundle_id,
        instruction=instruction,
    )

    # Add first step (from fixture)
    cassette.add_step(sample_cassette_step)

    # Add second step (modified version)
    step2_pre = HoarePre(
        target_key="button-plus",
        target_exists=True,
        target_enabled=True,
        target_role="AXButton",
        role_compatible=True,
        frontmost_app="com.apple.calculator",
        no_blocking_modal=True,
        timestamp_ns=2000000,
    )
    step2_action = ActionCanonical(
        id=str(uuid4()),
        step_idx=1,
        kind="MUTATE",
        target_key="button-plus",
        action_type="click",
        payload={"x": 110, "y": 210},
        tier="T1",
        channel="C2",
        timestamp_ns=2000001,
        session_id="test-session",
    )
    step2_post = HoarePost(
        target_key="button-plus",
        confidence=0.92,
        tier_signals={"L0": 0.92, "L1": None, "L2": None, "L3": None},
        verified=True,
        timestamp_ns=2000002,
    )
    step2 = CassetteStep(
        step_idx=1,
        hoare_pre=step2_pre,
        action_canonical=step2_action,
        hoare_post=step2_post,
        screenshot_phash="def7890000000000000000000000000000000000000000000000000000000000",
        ax_subtree_hash="hash2",
        healed_selectors=[],
    )
    cassette.add_step(step2)

    # Add third step
    step3_pre = HoarePre(
        target_key="button-minus",
        target_exists=True,
        target_enabled=True,
        target_role="AXButton",
        role_compatible=True,
        frontmost_app="com.apple.calculator",
        no_blocking_modal=True,
        timestamp_ns=3000000,
    )
    step3_action = ActionCanonical(
        id=str(uuid4()),
        step_idx=2,
        kind="MUTATE",
        target_key="button-minus",
        action_type="click",
        payload={"x": 120, "y": 220},
        tier="T1",
        channel="C2",
        timestamp_ns=3000001,
        session_id="test-session",
    )
    step3_post = HoarePost(
        target_key="button-minus",
        confidence=0.89,
        tier_signals={"L0": 0.89, "L1": None, "L2": None, "L3": None},
        verified=True,
        timestamp_ns=3000002,
    )
    step3 = CassetteStep(
        step_idx=2,
        hoare_pre=step3_pre,
        action_canonical=step3_action,
        hoare_post=step3_post,
        screenshot_phash="abc3450000000000000000000000000000000000000000000000000000000000",
        ax_subtree_hash="hash3",
        healed_selectors=[],
    )
    cassette.add_step(step3)

    return cassette
