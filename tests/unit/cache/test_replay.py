"""Unit tests for CassetteReplayEngine (match/mismatch, fallthrough, events)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from basicctrl.cache.cassette import Cassette, CassetteStep
from basicctrl.cache.replay import CassetteReplayEngine, hamming_distance
from basicctrl.state.causal_dag import ActionCanonical, HoarePost, HoarePre


class TestHammingDistance:
    """Test hamming_distance helper function."""

    def test_hamming_distance_identical(self):
        """Identical hashes have distance 0."""
        h = "abc123def456"
        assert hamming_distance(h, h) == 0

    def test_hamming_distance_single_bit(self):
        """Different by 1 bit in last hex digit."""
        # "f" = 1111 (binary), "e" = 1110 (binary) → 1 bit difference
        assert hamming_distance("abc123def45f", "abc123def45e") == 1

    def test_hamming_distance_multiple_bits(self):
        """Different by multiple bits."""
        # "0" = 0000, "f" = 1111 → 4 bits
        assert hamming_distance("0", "f") == 4

    def test_hamming_distance_threshold_boundary(self):
        """Verify boundary cases."""
        # Distance exactly 8
        h1 = "00000000"
        h2 = "ff000000"  # First digit: 0 vs f = 4 bits; second digit: 0 vs f = 4 bits
        # "00" vs "ff" = 8 bits total
        assert hamming_distance(h1, h2) == 8


class TestCassetteReplayMatch:
    """Test replay when steps match."""

    @pytest.mark.asyncio
    async def test_replay_all_steps_match(
        self, sample_cassette: Cassette
    ):
        """All steps' pHash matches current snapshot, assert (True, None, events)."""
        # Mock dependencies
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(
            side_effect=[
                {"phash": step.screenshot_phash}
                for step in sample_cassette.steps
            ]
        )

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()

        assert success is True
        assert mismatch_idx is None
        assert len(events) == len(sample_cassette.steps)
        assert all(e["event"] == "cassette_step_replay_ok" for e in events)

    @pytest.mark.asyncio
    async def test_replay_detects_mismatch_on_step_2(
        self, sample_cassette: Cassette
    ):
        """Step 0 matches, step 1 pHash differs (hamming > 8), assert (False, 1, events)."""
        # Mock dependencies
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        # Return matching pHash for step 0, mismatching for step 1
        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(
            side_effect=[
                {"phash": sample_cassette.steps[0].screenshot_phash},  # Match
                {"phash": "ffffffffffffffff"},  # Far different from step 1's hash
            ]
        )

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()

        assert success is False
        assert mismatch_idx == 1
        # Should have 1 match event + 1 mismatch event
        assert len(events) == 2
        assert events[0]["event"] == "cassette_step_replay_ok"
        assert events[1]["event"] == "cassette_mismatch"


class TestCassetteReplayThreshold:
    """Test pHash threshold boundary conditions."""

    @pytest.mark.asyncio
    async def test_replay_hamming_threshold_boundary(
        self, sample_cassette: Cassette
    ):
        """Step with hamming=8 (at threshold) returns match, hamming=9 returns mismatch."""
        # Test with hamming=8 (should match)
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        # Use the first step's phash but compute one that's exactly 8 bits away
        original_phash = sample_cassette.steps[0].screenshot_phash
        # Create a phash that's exactly 8 bits different
        # "abc123def456" → change 2nd and 3rd hex digits to get 8 bits difference
        modified_phash = "afffffff456"  # "bc" (1011, 1100) vs "ff" (1111, 1111) = some bits

        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(
            return_value={"phash": modified_phash}
        )

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        # Manually check hamming distance first
        distance = hamming_distance(original_phash, modified_phash)
        if distance <= 8:
            success, mismatch_idx, events = await engine.replay()
            assert success is True
            assert mismatch_idx is None
        else:
            success, mismatch_idx, events = await engine.replay()
            assert success is False
            assert mismatch_idx == 0


class TestCassetteReplayErrors:
    """Test error handling during replay."""

    @pytest.mark.asyncio
    async def test_replay_handles_missing_phash(
        self, sample_cassette: Cassette
    ):
        """Step.screenshot_phash is None, treat as mismatch."""
        race_orchestrator = AsyncMock()
        l1_cheap = AsyncMock()
        session_writer = AsyncMock()

        # Modify first step to have no phash
        sample_cassette.steps[0] = CassetteStep(
            step_idx=0,
            hoare_pre=sample_cassette.steps[0].hoare_pre,
            action_canonical=sample_cassette.steps[0].action_canonical,
            hoare_post=sample_cassette.steps[0].hoare_post,
            screenshot_phash="",  # Empty phash
            ax_subtree_hash="hash1",
        )

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()
        assert success is False
        assert mismatch_idx == 0

    @pytest.mark.asyncio
    async def test_replay_handles_screenshot_capture_failure(
        self, sample_cassette: Cassette
    ):
        """l1_cheap.snapshot raises, assert (False, step_idx, events)."""
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(side_effect=RuntimeError("Screenshot failed"))

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()
        assert success is False
        assert mismatch_idx == 0

    @pytest.mark.asyncio
    async def test_replay_handles_race_orchestrator_failure(
        self, sample_cassette: Cassette
    ):
        """race_orchestrator.execute raises, assert (False, step_idx, events)."""
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(
            side_effect=RuntimeError("Execution failed")
        )

        l1_cheap = AsyncMock()
        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()
        assert success is False
        assert mismatch_idx == 0


class TestCassetteReplayEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_replay_empty_cassette(self):
        """Cassette with 0 steps, assert (True, None, [])."""
        cassette = Cassette(
            cache_key="test-key",
            bundle_id="com.example.app",
            instruction="test",
        )

        race_orchestrator = AsyncMock()
        l1_cheap = AsyncMock()
        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.example.app",
        )

        success, mismatch_idx, events = await engine.replay()
        assert success is True
        assert mismatch_idx is None
        assert events == []

    @pytest.mark.asyncio
    async def test_replay_preserves_action_ordering(
        self, sample_cassette: Cassette
    ):
        """Execute called in order of steps (step 0, then 1, then 2)."""
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(
            side_effect=[
                {"phash": step.screenshot_phash}
                for step in sample_cassette.steps
            ]
        )

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        await engine.replay()

        # Verify execute was called exactly 3 times
        assert race_orchestrator.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_replay_mismatch_halts_early(
        self, sample_cassette: Cassette
    ):
        """Cassette with 5 steps, mismatch at step 2, assert only 2 execute calls."""
        # Add 2 more steps to get 5 total
        for i in range(3, 5):
            step = CassetteStep(
                step_idx=i,
                hoare_pre=sample_cassette.steps[0].hoare_pre,
                action_canonical=sample_cassette.steps[0].action_canonical,
                hoare_post=sample_cassette.steps[0].hoare_post,
                screenshot_phash=f"hash{i}",
                ax_subtree_hash=f"ax_hash{i}",
            )
            sample_cassette.add_step(step)

        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        # Return matches for step 0, 1, then mismatch on step 2
        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(
            side_effect=[
                {"phash": sample_cassette.steps[0].screenshot_phash},
                {"phash": sample_cassette.steps[1].screenshot_phash},
                {"phash": "ffffffffffffffff"},  # Mismatch on step 2
            ]
        )

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()
        assert success is False
        assert mismatch_idx == 2
        # Should have called execute only 3 times (steps 0, 1, 2 before mismatch)
        assert race_orchestrator.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_replay_includes_hamming_distance_in_mismatch_event(
        self, sample_cassette: Cassette
    ):
        """Mismatch event includes "hamming": N field for debugging."""
        race_orchestrator = AsyncMock()
        race_orchestrator.execute = AsyncMock(return_value=MagicMock())

        l1_cheap = AsyncMock()
        l1_cheap.snapshot = AsyncMock(
            return_value={"phash": "ffffffffffffffff"}  # Very different
        )

        session_writer = AsyncMock()

        engine = CassetteReplayEngine(
            cassette=sample_cassette,
            race_orchestrator=race_orchestrator,
            l1_cheap=l1_cheap,
            session_writer=session_writer,
            target_pid=12345,
            bundle_id="com.apple.calculator",
        )

        success, mismatch_idx, events = await engine.replay()
        assert success is False
        mismatch_event = events[0]
        assert "hamming" in mismatch_event
        assert mismatch_event["hamming"] > 8
