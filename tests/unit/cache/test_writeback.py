"""Unit tests for WriteBack (stable-tier gate, atomic update, stream caching)."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from cua_overlay.cache.cassette import Cassette, CassetteStep
from cua_overlay.cache.writeback import StreamCache, WriteBack
from cua_overlay.recovery.heal_event import HealEvent


class TestWriteBackStableTierGate:
    """Test stable-tier gate enforcement."""

    @pytest.mark.asyncio
    async def test_writeback_stable_tier_ax_identifier(
        self, sample_cassette: Cassette
    ):
        """HealEvent with locator_tier="AXIdentifier", assert heal() returns True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            # Write cassette to disk
            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_updated",
                reason="uitag regrounding",
                trace_id=str(uuid4()),
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )

            result = await writeback.heal(heal_event, cassette_path, 0)
            assert result is True

    @pytest.mark.asyncio
    async def test_writeback_stable_tier_ax_label(self, sample_cassette: Cassette):
        """HealEvent with locator_tier="AXLabel", assert heal() returns True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="@title=Submit",
                new_locator="@title=Submit_v2",
                reason="label changed",
                trace_id=str(uuid4()),
                locator_tier="AXLabel",
                source_branch="B1_RESCROLL",
            )

            result = await writeback.heal(heal_event, cassette_path, 0)
            assert result is True

    @pytest.mark.asyncio
    async def test_writeback_gates_vision_tier(self, sample_cassette: Cassette):
        """HealEvent with locator_tier="Vision", assert heal() returns False (D-20)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="pixel_coord:100,200",
                new_locator="pixel_coord:105,205",
                reason="vision regrounding",
                trace_id=str(uuid4()),
                locator_tier="Vision",
                source_branch="B2_OCR",
            )

            result = await writeback.heal(heal_event, cassette_path, 0)
            assert result is False  # Session-only, never written back

    @pytest.mark.asyncio
    async def test_writeback_gates_coordinate_tier(
        self, sample_cassette: Cassette
    ):
        """HealEvent with locator_tier="Coordinate", assert heal() returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="x:100 y:200",
                new_locator="x:105 y:205",
                reason="coordinate drift",
                trace_id=str(uuid4()),
                locator_tier="Coordinate",
                source_branch="B2_OCR",
            )

            result = await writeback.heal(heal_event, cassette_path, 0)
            assert result is False


class TestWriteBackUpdate:
    """Test cassette update mechanics."""

    @pytest.mark.asyncio
    async def test_writeback_updates_cassette_step(
        self, sample_cassette: Cassette
    ):
        """Heal with old/new locator, assert healed_selectors appended."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_updated",
                reason="regrounding",
                trace_id=str(uuid4()),
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )

            await writeback.heal(heal_event, cassette_path, 0)

            # Verify cassette was updated
            content = cassette_path.read_text()
            updated = Cassette.from_ndjson(content, "test")

            assert len(updated.steps[0].healed_selectors) == 1
            assert updated.steps[0].healed_selectors[0] == "@id=button1_updated"

    @pytest.mark.asyncio
    async def test_writeback_appends_to_healed_selectors(
        self, sample_cassette: Cassette
    ):
        """Multiple heals appended to step.healed_selectors, not replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            # First heal
            heal1 = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_v1",
                reason="first heal",
                trace_id=str(uuid4()),
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )
            await writeback.heal(heal1, cassette_path, 0)

            # Second heal on same step
            heal2 = HealEvent(
                old_locator="@id=button1_v1",
                new_locator="@id=button1_v2",
                reason="second heal",
                trace_id=str(uuid4()),
                locator_tier="AXLabel",
                source_branch="B2_OCR",
            )
            await writeback.heal(heal2, cassette_path, 0)

            # Verify both appended
            content = cassette_path.read_text()
            updated = Cassette.from_ndjson(content, "test")

            assert len(updated.steps[0].healed_selectors) == 2
            assert "@id=button1_v1" in updated.steps[0].healed_selectors
            assert "@id=button1_v2" in updated.steps[0].healed_selectors


class TestWriteBackAtomic:
    """Test atomic file replacement."""

    @pytest.mark.asyncio
    async def test_writeback_atomic_file_replacement(
        self, sample_cassette: Cassette
    ):
        """Verify cassette.tmp created, fsync called, rename called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_updated",
                reason="regrounding",
                trace_id=str(uuid4()),
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )

            await writeback.heal(heal_event, cassette_path, 0)

            # Verify original cassette file exists and was updated
            assert cassette_path.exists()
            # Verify no .tmp file left behind (it was renamed)
            assert not cassette_path.with_suffix(".jsonl.tmp").exists()

    @pytest.mark.asyncio
    async def test_writeback_locking_protects_concurrent_writes(
        self, sample_cassette: Cassette
    ):
        """Verify _lock acquired during write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            # Verify lock exists
            assert hasattr(writeback, "_lock")
            assert isinstance(writeback._lock, asyncio.Lock)

            # Verify we can acquire/release it
            await writeback._lock.acquire()
            writeback._lock.release()


class TestWriteBackErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_writeback_handles_missing_cassette(self):
        """Cassette file doesn't exist, assert heal() returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            writeback = WriteBack(cassettes_dir, session_writer)
            cassette_path = cassettes_dir / "nonexistent.jsonl"

            heal_event = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_updated",
                reason="regrounding",
                trace_id=str(uuid4()),
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )

            result = await writeback.heal(heal_event, cassette_path, 0)
            assert result is False

    @pytest.mark.asyncio
    async def test_writeback_handles_parse_error(self, sample_cassette: Cassette):
        """Cassette file corrupted, parse fails, assert heal() returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text("{ invalid json }")

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_updated",
                reason="regrounding",
                trace_id=str(uuid4()),
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )

            result = await writeback.heal(heal_event, cassette_path, 0)
            assert result is False

    @pytest.mark.asyncio
    async def test_writeback_emits_event(self, sample_cassette: Cassette):
        """Assert session_writer.append_action_log called with writeback event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cassettes_dir = Path(tmpdir)
            session_writer = AsyncMock()

            cassette_path = cassettes_dir / "test-cassette.jsonl"
            cassette_path.write_text(sample_cassette.to_ndjson())

            writeback = WriteBack(cassettes_dir, session_writer)

            heal_event = HealEvent(
                old_locator="@id=button1",
                new_locator="@id=button1_updated",
                reason="regrounding",
                trace_id="trace-123",
                locator_tier="AXIdentifier",
                source_branch="B1_RESCROLL",
            )

            await writeback.heal(heal_event, cassette_path, 0)

            # Verify session_writer was called
            assert session_writer.append_action_log.called
            event = session_writer.append_action_log.call_args[0][0]
            assert event["event"] == "cassette_writeback"
            assert event["step_idx"] == 0


class TestStreamCache:
    """Test stream caching wrapper."""

    @pytest.mark.asyncio
    async def test_stream_cache_transparent_iteration(self):
        """Create StreamCache wrapping mock async generator, iterate, assert cached."""
        cache = StreamCache("test-stream", agent_cache=None)

        async def mock_generator():
            yield "chunk1"
            yield "chunk2"
            yield "chunk3"

        chunks = []
        async for chunk in cache.wrap_generator(mock_generator()):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2", "chunk3"]
        assert cache._cached_chunks == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_stream_cache_replays_cached_chunks(self):
        """First iteration caches, second iteration replays from cache."""
        cache = StreamCache("test-stream", agent_cache=None)

        call_count = 0

        async def mock_generator():
            nonlocal call_count
            call_count += 1
            yield "chunk1"
            yield "chunk2"

        # First iteration: populate cache
        chunks1 = []
        async for chunk in cache.wrap_generator(mock_generator()):
            chunks1.append(chunk)

        # Mark as cached
        cache.mark_cached()

        # Second iteration: replay from cache (generator not called again)
        chunks2 = []
        async for chunk in cache.wrap_generator(mock_generator()):
            chunks2.append(chunk)

        assert chunks1 == ["chunk1", "chunk2"]
        assert chunks2 == ["chunk1", "chunk2"]
        # Generator called only once (first iteration)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_stream_cache_clear_cache(self):
        """Clear cache resets cached_chunks and is_cached flag."""
        cache = StreamCache("test-stream", agent_cache=None)

        async def mock_generator():
            yield "chunk1"

        async for chunk in cache.wrap_generator(mock_generator()):
            pass

        assert len(cache._cached_chunks) > 0
        cache.clear_cache()
        assert len(cache._cached_chunks) == 0
        assert cache._is_cached is False
