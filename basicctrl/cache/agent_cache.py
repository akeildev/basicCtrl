"""AgentCache: SHA-256 keyed, disk-persisted, thread-safe cache of cassettes.

Per CONTEXT.md D-17: AgentCache is the Stagehand-style cache that stores
cassettes (replay artifacts) on disk under ~/.cua/sessions/<id>/cassettes/
with SHA-256 keys derived from (bundle_id, role_path, instruction).

Implements asyncio.Lock for thread-safe concurrent access.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from basicctrl.cache.cassette import Cassette
from basicctrl.cache.key import compute_cache_key


log = logging.getLogger(__name__)


class AgentCache:
    """Thread-safe cache of cassettes persisted to disk.

    Attributes:
        _cassettes_dir: Path to cassettes directory (created if needed)
        _lock: asyncio.Lock protecting concurrent access
        _cache: in-memory dict[cache_key -> Cassette] for fast lookups
    """

    def __init__(self, session_dir: Path):
        """Initialize AgentCache.

        Args:
            session_dir: Path to session directory (e.g., ~/.cua/sessions/<id>/)
        """
        self._cassettes_dir = session_dir / "cassettes"
        self._cassettes_dir.mkdir(parents=True, exist_ok=True)

        self._lock = asyncio.Lock()
        self._cache: dict[str, Cassette] = {}

    async def get(
        self,
        bundle_id: str,
        role_path: str,
        instruction: str,
    ) -> Optional[Cassette]:
        """Get cassette by (bundle_id, role_path, instruction).

        Returns cassette from in-memory cache if present; otherwise checks disk.
        Returns None on cache miss or parse error (graceful degradation).

        Args:
            bundle_id: app bundle ID
            role_path: role path (e.g., "AXApplication > AXWindow > AXButton")
            instruction: user instruction

        Returns:
            Cassette if found, None otherwise
        """
        cache_key = compute_cache_key(bundle_id, role_path, instruction)

        async with self._lock:
            # Check in-memory cache
            if cache_key in self._cache:
                return self._cache[cache_key]

            # Check disk
            cassette_path = self._cassettes_dir / f"{cache_key}.jsonl"
            if not cassette_path.exists():
                return None

            # Load from disk
            try:
                content = cassette_path.read_text(encoding="utf-8")
                cassette = Cassette.from_ndjson(content, cache_key)
                self._cache[cache_key] = cassette
                return cassette
            except (json.JSONDecodeError, ValueError) as e:
                log.warning(f"Failed to load cassette {cache_key}: {e}")
                return None
            except Exception as e:
                log.error(f"Unexpected error loading cassette {cache_key}: {e}")
                return None

    async def put(self, cassette: Cassette) -> None:
        """Store cassette to disk and in-memory cache.

        Uses atomic write pattern: write to .tmp, fsync, rename.

        Args:
            cassette: Cassette instance to persist
        """
        cassette_path = self._cassettes_dir / f"{cassette.cache_key}.jsonl"

        async with self._lock:
            try:
                # Serialize cassette
                ndjson_content = cassette.to_ndjson()

                # Write to temporary file
                tmp_path = cassette_path.with_suffix(".jsonl.tmp")
                tmp_path.write_text(ndjson_content, encoding="utf-8")

                # Fsync for durability
                with tmp_path.open("rb") as f:
                    import os

                    os.fsync(f.fileno())

                # Atomic rename
                tmp_path.rename(cassette_path)

                # Update in-memory cache
                self._cache[cassette.cache_key] = cassette
            except Exception as e:
                log.error(f"Failed to put cassette {cassette.cache_key}: {e}")

    async def clear(self, cache_key: str) -> None:
        """Remove cassette from disk and in-memory cache.

        Args:
            cache_key: SHA-256 cache key
        """
        cassette_path = self._cassettes_dir / f"{cache_key}.jsonl"

        async with self._lock:
            try:
                if cassette_path.exists():
                    cassette_path.unlink()
                if cache_key in self._cache:
                    del self._cache[cache_key]
            except Exception as e:
                log.error(f"Failed to clear cassette {cache_key}: {e}")
