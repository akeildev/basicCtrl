"""End-to-end episodic memory: index recipe, lookup similar task.

Gate: CUA_RUN_E2E_MEMORY=1

Verifies that episodic memory (FAISS vector store) can:

  1. Index a Recipe after a task completes.
  2. Lookup a similar task and return ≥1 hit with similarity > 0.85.

Uses a temporary FAISS file path so each run gets a fresh vector store.

Schema reference (cua_overlay/learning/schemas.py):
  Recipe(name, app_bundle_id, params, preconditions, steps, success_criteria, created_ts)
  RecipeStep(idx, action, preconditions, on_failure)
  RecipePrecondition(expression, expected_value, confidence)

EpisodicMemory API (cua_overlay/state/episodic.py):
  EpisodicMemory(faiss_path=..., embedding_dim=384)
  index_recipe(recipe, app_bundle_id, task_class, state_fingerprint, embedding, source_text)
  lookup(query: EpisodicQuery) -> list[EpisodicHit]
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_MEMORY") != "1",
        reason="episodic memory e2e; set CUA_RUN_E2E_MEMORY=1 to run",
    ),
]


def _build_recipe(name: str = "calculator_add") -> "Recipe":
    """Build a minimal valid Recipe per the actual cua_overlay.learning schema."""
    from cua_overlay.learning import Recipe, RecipeStep
    from cua_overlay.state.causal_dag import ActionCanonical

    action = ActionCanonical(
        id=f"act-{uuid.uuid4().hex[:8]}",
        step_idx=0,
        kind="MUTATE",
        target_key="btn_5",
        action_type="click",
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id="test-mem-session",
    )
    step = RecipeStep(
        idx=0,
        action=action,
        preconditions=[],
        on_failure=["retry_once"],
    )
    return Recipe(
        name=name,
        app_bundle_id="com.apple.calculator",
        params=[],
        preconditions=[],
        steps=[step],
        success_criteria=["Calculator display reads 5"],
        created_ts=time.time(),
    )


@pytest.fixture
def temp_faiss_path():
    """Yield a temporary FAISS path, auto-deleted after test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / f"test_episodic_{uuid.uuid4().hex}.faiss"
        yield fpath


@pytest.mark.asyncio
async def test_episodic_memory_index_and_lookup(temp_faiss_path: Path) -> None:
    """Index a recipe, lookup with same embedding → expect ≥1 hit at high similarity."""
    from cua_overlay.state.episodic import EpisodicMemory, EpisodicQuery

    memory = EpisodicMemory(faiss_path=str(temp_faiss_path))
    recipe = _build_recipe("calculator_add_test1")

    # Use a deterministic embedding so lookup with the same vector is a near-hit
    embedding = [0.01 * (i % 10) for i in range(384)]

    await memory.index_recipe(
        recipe=recipe,
        app_bundle_id="com.apple.calculator",
        task_class="calculator_math",
        state_fingerprint="test-fp-1",
        embedding=embedding,
        source_text="click button 5 in Calculator",
    )

    # Lookup with the SAME embedding (perfect match)
    query = EpisodicQuery(
        app_bundle_id="com.apple.calculator",
        task_class="calculator_math",
        state_fingerprint="test-fp-1",
        query_embedding=embedding,
        top_k=3,
    )
    hits = await memory.lookup(query)

    assert isinstance(hits, list), f"lookup() must return list; got {type(hits)}"
    assert len(hits) >= 1, "expected ≥1 hit when querying with the indexed embedding"
    top = hits[0]
    assert top.similarity > 0.85, (
        f"identical-embedding lookup should produce similarity>0.85; got {top.similarity}"
    )


@pytest.mark.asyncio
async def test_episodic_memory_multiple_recipes(temp_faiss_path: Path) -> None:
    """Index two recipes; lookup recovers the matching one preferentially."""
    from cua_overlay.state.episodic import EpisodicMemory, EpisodicQuery

    memory = EpisodicMemory(faiss_path=str(temp_faiss_path))

    # Two distinct embeddings
    embed_a = [0.01 * (i % 10) for i in range(384)]
    embed_b = [0.5 + 0.001 * i for i in range(384)]

    await memory.index_recipe(
        recipe=_build_recipe("recipe_a"),
        app_bundle_id="com.apple.calculator",
        task_class="calculator_math",
        state_fingerprint="fp-a",
        embedding=embed_a,
        source_text="click 1 then 1 then equals",
    )
    await memory.index_recipe(
        recipe=_build_recipe("recipe_b"),
        app_bundle_id="com.apple.calculator",
        task_class="calculator_math",
        state_fingerprint="fp-b",
        embedding=embed_b,
        source_text="click 2 then 2 then equals",
    )

    # Query with embed_a; expect recipe_a as top hit
    query = EpisodicQuery(
        app_bundle_id="com.apple.calculator",
        task_class="calculator_math",
        state_fingerprint="fp-a",
        query_embedding=embed_a,
        top_k=2,
    )
    hits = await memory.lookup(query)
    assert len(hits) >= 1
    top = hits[0]
    assert top.recipe is not None
    assert top.recipe.name == "recipe_a", (
        f"top hit should be the matching-embedding recipe; got {top.recipe.name}"
    )
