"""STATE-04 episodic memory unit tests — EpisodicMemory schema stubs.

Per Wave 0 pattern: pytest.importorskip skips cleanly until impl ships.
Tests lock the system-wide episodic memory contract.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

pytest.importorskip("cua_overlay.state.episodic")

from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.state.episodic import EpisodicHit, EpisodicMemory, EpisodicQuery


def _build_action(step_idx: int = 0) -> ActionCanonical:
    """Helper to build a minimal ActionCanonical."""
    return ActionCanonical(
        id=f"action-{step_idx}",
        step_idx=step_idx,
        kind="READ",
        target_key="button://app/target",
        action_type="click",
        payload={"x": 100, "y": 100},
        timestamp_ns=0,
        session_id="test-session",
    )


def _build_recipe(
    name: str = "test_recipe",
    bundle_id: str = "com.test.app",
):
    """Helper to build a Recipe."""
    # Deferred import to avoid circular dependency at module load time
    from cua_overlay.learning import Recipe, RecipePrecondition, RecipeStep

    action = _build_action(step_idx=0)
    step = RecipeStep(
        idx=0,
        action=action,
        preconditions=[],
        on_failure=[],
    )
    return Recipe(
        name=name,
        app_bundle_id=bundle_id,
        params=[],
        preconditions=[],
        steps=[step],
        success_criteria=["done"],
        created_ts=1234567890.0,
    )


@pytest.mark.unit
def test_episodic_query_creation() -> None:
    """EpisodicQuery stores app_bundle_id, task_class, state_fingerprint, top_k."""
    query = EpisodicQuery(
        app_bundle_id="com.google.Chrome",
        task_class="web_search",
        state_fingerprint="abc123def456",
        query_embedding=[0.1, 0.2, 0.3],
        top_k=3,
    )
    assert query.app_bundle_id == "com.google.Chrome"
    assert query.task_class == "web_search"
    assert query.top_k == 3


@pytest.mark.unit
def test_episodic_query_frozen() -> None:
    """EpisodicQuery is frozen."""
    query = EpisodicQuery(
        app_bundle_id="com.test.app",
        task_class="test_class",
        state_fingerprint="xyz",
        query_embedding=[0.5],
    )
    with pytest.raises(ValidationError, match="frozen"):
        query.top_k = 5  # type: ignore[misc]


@pytest.mark.unit
def test_episodic_hit_with_recipe_and_metadata() -> None:
    """EpisodicHit bundles Recipe + similarity + metadata (success/failure/quarantine)."""
    recipe = _build_recipe()
    hit = EpisodicHit(
        recipe=recipe,
        similarity=0.92,
        embedding_source_text="search for xyz on google",
        success_count=3,
        failure_count=0,
        quarantined=False,
    )
    assert hit.recipe.name == "test_recipe"
    assert hit.similarity == 0.92
    assert hit.success_count == 3
    assert hit.failure_count == 0
    assert hit.quarantined is False


@pytest.mark.unit
def test_episodic_hit_quarantine_flag() -> None:
    """EpisodicHit tracks quarantine on >2 failures (D-19 P22 mitigation)."""
    recipe = _build_recipe()
    hit = EpisodicHit(
        recipe=recipe,
        similarity=0.60,
        embedding_source_text="test",
        success_count=0,
        failure_count=3,
        quarantined=True,
    )
    assert hit.quarantined is True
    assert hit.failure_count == 3


@pytest.mark.unit
def test_episodic_hit_similarity_bounds() -> None:
    """EpisodicHit.similarity is in [0.0, 1.0]."""
    recipe = _build_recipe()
    hit = EpisodicHit(
        recipe=recipe,
        similarity=0.85,
        embedding_source_text="test",
    )
    assert hit.similarity == 0.85

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        EpisodicHit(
            recipe=recipe,
            similarity=1.5,  # type: ignore[arg-type]
            embedding_source_text="test",
        )


@pytest.mark.unit
def test_episodic_hit_frozen() -> None:
    """EpisodicHit is frozen."""
    recipe = _build_recipe()
    hit = EpisodicHit(
        recipe=recipe,
        similarity=0.90,
        embedding_source_text="test",
    )
    with pytest.raises(ValidationError, match="frozen"):
        hit.success_count = 10  # type: ignore[misc]


@pytest.mark.unit
def test_episodic_memory_stub() -> None:
    """EpisodicMemory initializes with optional faiss_path override."""
    from pathlib import Path

    mem = EpisodicMemory()
    assert mem.faiss_path == Path("~/.cua/episodic.faiss").expanduser()

    custom_path = Path("/tmp/test_index.faiss")
    mem_custom = EpisodicMemory(faiss_path=str(custom_path))
    assert mem_custom.faiss_path == custom_path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episodic_memory_index_recipe() -> None:
    """EpisodicMemory.index_recipe() adds recipe to FAISS + metadata."""
    import tempfile
    from pathlib import Path

    recipe = _build_recipe()

    # Use temp directory for this test
    with tempfile.TemporaryDirectory() as tmpdir:
        mem = EpisodicMemory(faiss_path=str(Path(tmpdir) / "test.faiss"))

        # Index the recipe
        embedding = [0.1] * 384  # Mock 384-dim embedding
        await mem.index_recipe(
            recipe=recipe,
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            embedding=embedding,
            source_text="test recipe text",
        )

        # Verify metadata was stored
        assert len(mem._metadata) > 0
        assert mem._index.ntotal == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episodic_memory_lookup_returns_hits() -> None:
    """EpisodicMemory.lookup() returns top-K recipes with similarity > 0.85."""
    import tempfile
    from pathlib import Path

    recipe = _build_recipe()

    with tempfile.TemporaryDirectory() as tmpdir:
        mem = EpisodicMemory(faiss_path=str(Path(tmpdir) / "test.faiss"))

        # Index a recipe
        embedding = [0.1] * 384
        await mem.index_recipe(
            recipe=recipe,
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            embedding=embedding,
            source_text="test recipe text",
        )

        # Lookup with very similar embedding (should hit)
        query_embedding = [0.1] * 384  # Identical embedding
        query = EpisodicQuery(
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            query_embedding=query_embedding,
            top_k=3,
        )

        hits = await mem.lookup(query)

        # Should get a hit (identical embedding = distance 0, similarity = 1.0)
        assert len(hits) > 0
        assert hits[0].similarity >= 0.85
        assert hits[0].recipe.name == "test_recipe"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episodic_memory_quarantine_on_failures() -> None:
    """EpisodicMemory: failure_count > 2 → quarantined=True (D-19)."""
    import tempfile
    from pathlib import Path

    recipe = _build_recipe()

    with tempfile.TemporaryDirectory() as tmpdir:
        mem = EpisodicMemory(faiss_path=str(Path(tmpdir) / "test.faiss"))

        # Index recipe
        embedding = [0.1] * 384
        await mem.index_recipe(
            recipe=recipe,
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            embedding=embedding,
            source_text="test recipe text",
        )

        # Mark 3 failures
        mem.mark_recipe_failure(row_idx=0)
        mem.mark_recipe_failure(row_idx=0)
        mem.mark_recipe_failure(row_idx=0)

        # Verify quarantined flag is set
        assert mem._metadata["0"]["failure_count"] == 3
        assert mem._metadata["0"]["quarantined"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episodic_memory_success_tracking() -> None:
    """EpisodicMemory: mark_recipe_success() increments success_count."""
    import tempfile
    from pathlib import Path

    recipe = _build_recipe()

    with tempfile.TemporaryDirectory() as tmpdir:
        mem = EpisodicMemory(faiss_path=str(Path(tmpdir) / "test.faiss"))

        # Index recipe
        embedding = [0.1] * 384
        await mem.index_recipe(
            recipe=recipe,
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            embedding=embedding,
            source_text="test recipe text",
        )

        # Mark 2 successes
        mem.mark_recipe_success(row_idx=0)
        mem.mark_recipe_success(row_idx=0)

        # Verify success_count updated
        assert mem._metadata["0"]["success_count"] == 2
        assert mem._metadata["0"]["failure_count"] == 0
        assert mem._metadata["0"]["quarantined"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episodic_memory_similarity_threshold() -> None:
    """EpisodicMemory.lookup() filters by similarity > 0.85 threshold."""
    import tempfile
    from pathlib import Path

    recipe = _build_recipe()

    with tempfile.TemporaryDirectory() as tmpdir:
        mem = EpisodicMemory(faiss_path=str(Path(tmpdir) / "test.faiss"))

        # Index recipe with embedding [0.1, 0.1, ...]
        embedding = [0.1] * 384
        await mem.index_recipe(
            recipe=recipe,
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            embedding=embedding,
            source_text="test recipe text",
        )

        # Lookup with different embedding (should NOT hit if distance is too large)
        # Create a very different embedding (far away in L2 space)
        query_embedding = [0.9] * 384  # Opposite direction
        query = EpisodicQuery(
            app_bundle_id="com.test.app",
            task_class="test_task",
            state_fingerprint="abc123",
            query_embedding=query_embedding,
            top_k=3,
        )

        hits = await mem.lookup(query)

        # Very different embedding should NOT meet 0.85 threshold
        # (L2 distance will be large, so similarity = 1/(1+dist) will be small)
        # Note: This is a heuristic test; actual similarity depends on embedding values
        assert len(hits) == 0 or hits[0].similarity < 0.85
