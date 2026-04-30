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
    mem = EpisodicMemory()
    assert mem.faiss_path == "~/.cua/episodic.faiss"

    mem_custom = EpisodicMemory(faiss_path="/custom/path/index.faiss")
    assert mem_custom.faiss_path == "/custom/path/index.faiss"
