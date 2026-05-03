"""ACT-03 — IdempotencyTokenStore atomicity tests (D-16, D-17, D-18)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from basicctrl.actions.idempotency import ChannelClaim, IdempotencyTokenStore
from basicctrl.persist.session_writer import SessionWriter


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyTokenStore:
    sw = SessionWriter(base=tmp_path)
    return IdempotencyTokenStore(sw)


async def test_try_claim_first_wins(store: IdempotencyTokenStore) -> None:
    claim = await store.try_claim("act-1", "C2")
    assert isinstance(claim, ChannelClaim)
    assert claim.claimed_by_channel == "C2"
    second = await store.try_claim("act-1", "C5")
    assert second is None


async def test_concurrent_claim_exactly_one_winner(
    store: IdempotencyTokenStore,
) -> None:
    results = await asyncio.gather(
        *[store.try_claim("act-2", ch) for ch in ("C1", "C2", "C3", "C4", "C5")]
    )
    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1, f"expected 1 winner, got {len(winners)}"
    assert len(losers) == 4


async def test_claim_written_to_ndjson(
    store: IdempotencyTokenStore, tmp_path: Path
) -> None:
    await store.try_claim("act-3", "C2")
    log_path = store._session.action_log_path  # noqa: SLF001 — test access
    lines = log_path.read_text().splitlines()
    assert any('"event": "idempotency_claim"' in ln for ln in lines)
    matched = [
        json.loads(ln)
        for ln in lines
        if '"action_id": "act-3"' in ln and '"event": "idempotency_claim"' in ln
    ]
    assert len(matched) == 1
    entry = matched[0]
    assert entry["channel"] == "C2"
    assert entry["claimed_at_ns"] > 0


async def test_is_claimed_lock_free_peek(store: IdempotencyTokenStore) -> None:
    claim = await store.try_claim("act-4", "C3")
    assert claim is not None
    # Lock-free peek must NOT acquire the lock — call it while another await
    # holds the lock to prove no deadlock.
    async with store._lock:  # noqa: SLF001
        peek = store.is_claimed("act-4")
        assert peek is not None
        assert peek.claimed_by_channel == "C3"


async def test_claim_timestamps_monotonic(store: IdempotencyTokenStore) -> None:
    a = await store.try_claim("act-5a", "C2")
    b = await store.try_claim("act-5b", "C2")
    c = await store.try_claim("act-5c", "C2")
    assert a is not None and b is not None and c is not None
    assert a.claimed_at_ns < b.claimed_at_ns < c.claimed_at_ns
