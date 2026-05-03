"""WriteBack: atomic cassette updates with stable-tier gate + stream caching.

Per CONTEXT.md D-20, D-21: WriteBack updates cassettes when healed selectors
are discovered, but ONLY for stable locator tiers (AXIdentifier, AXLabel,
AXTitle, AXRoleDescription). Vision-based and coordinate-based heals stay
session-only (never written back to canonical cassette per P23 mitigation).

Atomic file replacement pattern (write .tmp, fsync, rename) prevents corruption.
StreamCache transparently wraps async generators for chunk-level caching.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from basicctrl.cache.cassette import Cassette
from basicctrl.recovery.heal_event import HealEvent


log = logging.getLogger(__name__)


class WriteBack:
    """Atomic cassette write-back with stable-tier gate.

    Per D-20: Only stable-tier heals (AXIdentifier, AXLabel, AXTitle,
    AXRoleDescription) are written back to canonical cassettes. Vision and
    Coordinate heals are session-only.

    Attributes:
        _cassettes_dir: Path to cassettes directory
        _session_writer: SessionWriter for write-back events
        _lock: asyncio.Lock protecting concurrent writes
    """

    def __init__(self, cassettes_dir: Path, session_writer):
        """Initialize WriteBack.

        Args:
            cassettes_dir: Path to cassettes directory
            session_writer: SessionWriter for events
        """
        self._cassettes_dir = cassettes_dir
        self._session_writer = session_writer
        self._lock = asyncio.Lock()

    async def heal(
        self,
        heal_event: HealEvent,
        cassette_path: Path,
        step_idx: int,
    ) -> bool:
        """Update cassette with healed selector (stable-tier only).

        Per D-20: gates on stable-tier check. Vision and Coordinate heals
        return False (not written back).

        Args:
            heal_event: HealEvent with old_locator, new_locator, locator_tier
            cassette_path: Path to cassette file
            step_idx: which step to update

        Returns:
            True if heal was applied, False if stable-tier gated or error
        """
        # D-20: Gate on stable-tier
        if not heal_event.is_stable_tier():
            log.info(
                f"Heal gated (non-stable tier {heal_event.locator_tier}): "
                f"{heal_event.old_locator} → {heal_event.new_locator}"
            )
            return False

        async with self._lock:
            try:
                # Load cassette
                if not cassette_path.exists():
                    log.warning(f"Cassette file not found: {cassette_path}")
                    return False

                content = cassette_path.read_text(encoding="utf-8")
                cassette = Cassette.from_ndjson(
                    content,
                    cassette_path.stem.replace(".jsonl", ""),
                )

                # Find and update step
                if step_idx < 0 or step_idx >= len(cassette.steps):
                    log.warning(
                        f"Step index {step_idx} out of range (cassette has {len(cassette.steps)} steps)"
                    )
                    return False

                step = cassette.steps[step_idx]

                # Update target locator in the step (via action_canonical.target_key)
                # Note: In a full implementation, we'd update the actual locator in the
                # step's action or a linked locator field. For now, we append to healed_selectors.
                # Create a new step with updated healed_selectors
                updated_healed = list(step.healed_selectors)
                updated_healed.append(heal_event.new_locator)

                # Reconstruct step with updated healed_selectors
                from basicctrl.cache.cassette import CassetteStep

                updated_step = CassetteStep(
                    step_idx=step.step_idx,
                    hoare_pre=step.hoare_pre,
                    action_canonical=step.action_canonical,
                    hoare_post=step.hoare_post,
                    screenshot_phash=step.screenshot_phash,
                    ax_subtree_hash=step.ax_subtree_hash,
                    healed_selectors=updated_healed,
                )

                # Replace step in cassette
                cassette.steps[step_idx] = updated_step

                # Atomic write: .tmp → fsync → rename
                tmp_path = cassette_path.with_suffix(".jsonl.tmp")
                ndjson_content = cassette.to_ndjson()
                tmp_path.write_text(ndjson_content, encoding="utf-8")

                # Fsync for durability
                with tmp_path.open("rb") as f:
                    os.fsync(f.fileno())

                # Atomic rename
                tmp_path.rename(cassette_path)

                # Emit write-back event
                event = {
                    "event": "cassette_writeback",
                    "cache_key": cassette_path.stem.replace(".jsonl", ""),
                    "step_idx": step_idx,
                    "heal_tier": heal_event.locator_tier,
                    "old_locator": heal_event.old_locator,
                    "new_locator": heal_event.new_locator,
                    "trace_id": heal_event.trace_id,
                }
                await self._session_writer.append_action_log(event)

                log.info(
                    f"Cassette write-back: step {step_idx}, tier {heal_event.locator_tier}, "
                    f"{heal_event.old_locator} → {heal_event.new_locator}"
                )
                return True

            except Exception as e:
                log.error(f"Failed to heal cassette {cassette_path}: {e}")
                return False


class StreamCache:
    """Transparent caching wrapper for async generators.

    Per CACHE-03: wraps any async generator the agent consumes; transparently
    caches per-chunk and replays on cassette hit.

    Attributes:
        _stream_name: name of the stream (for logging/debugging)
        _agent_cache: AgentCache instance
        _cached_chunks: list of cached chunks
        _is_cached: whether we're replaying from cache
    """

    def __init__(self, stream_name: str, agent_cache):
        """Initialize StreamCache.

        Args:
            stream_name: name of the stream
            agent_cache: AgentCache instance (unused for now, future use)
        """
        self._stream_name = stream_name
        self._agent_cache = agent_cache
        self._cached_chunks: list[object] = []
        self._is_cached = False

    async def wrap_generator(
        self, generator: AsyncGenerator
    ) -> AsyncGenerator:
        """Wrap an async generator with transparent caching.

        First pass: yields from generator, caches chunks.
        Subsequent calls: replay from cache.

        Args:
            generator: async generator to wrap

        Yields:
            Chunks from generator (or cache on replay)
        """
        if self._is_cached:
            # Replay from cache
            for chunk in self._cached_chunks:
                yield chunk
        else:
            # First pass: cache chunks
            async for chunk in generator:
                self._cached_chunks.append(chunk)
                yield chunk

    def mark_cached(self) -> None:
        """Mark this stream as ready for replay."""
        self._is_cached = True

    def clear_cache(self) -> None:
        """Clear cached chunks."""
        self._cached_chunks.clear()
        self._is_cached = False
