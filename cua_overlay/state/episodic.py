"""STATE-04 — Episodic memory (FAISS vector store) + schema stubs.

Per D-18..D-20 (04-CONTEXT.md):

Episodic memory is a local FAISS IndexFlatL2 vector store keyed by
(app_bundle_id, task_class, state_fingerprint). Surfaces "I've done this
before" recipe matches BEFORE any LLM planning call.

Local-only storage: ~/.cua/episodic.faiss (file) + sidecar metadata JSON.
Embedding model: TBD at planner time (sentence-transformers small vs
Apple FM text vs OpenAI ada-002).

Wave 0 stubs only. FAISS integration + retrieval logic lands in Wave 4
(Phase 4 Plan 04-05..04-07).

Threat register:
  T-4-02: Recipe poisoning — mitigated via success_count/failure_count + quarantine
  T-4-08: EpisodicHit tracks success/failure; recipe quarantined on >2 failures
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from cua_overlay.learning import Recipe


class EpisodicQuery(BaseModel):
    """Per D-20: Query input to episodic memory lookup.

    Before planning, the cognition layer calls:
        episodic.lookup(query_state) -> list[EpisodicHit]

    Returns top-k recipes with similarity > 0.85 (empirically tuned
    per Stagehand AgentCache precedent).
    """

    model_config = ConfigDict(frozen=True)

    app_bundle_id: str
    task_class: str  # e.g., "web_search", "calculator_math", "spreadsheet_fill"
    state_fingerprint: str  # SHA-256 hash of current app state
    query_embedding: list[float]
    top_k: int = 3


class EpisodicHit(BaseModel):
    """Per D-20, D-19: One match from episodic memory lookup.

    D-19: Track success_count and failure_count per recipe. On >2 failures,
    quarantined=True (recipe surfaces as "low-confidence" only).

    success_count/failure_count: empirical hit/miss on actual replay
    embedding_source_text: text used to generate query_embedding (for
                           re-embedding if embedding model changes)
    similarity: cosine similarity (0.0-1.0) to the query
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    recipe: Recipe
    similarity: float = Field(..., ge=0.0, le=1.0)
    embedding_source_text: str
    success_count: int = 0
    failure_count: int = 0
    quarantined: bool = False


class EpisodicMemory:
    """Per D-18: FAISS local vector store wrapper for episodic recipe retrieval.

    Stub only in Wave 0. Implementation (Wave 4, Plan 04-05) adds:
    - IndexFlatL2 index from faiss-cpu 1.13.2
    - Local file at ~/.cua/episodic.faiss
    - Metadata sidecar JSON (success_count, failure_count, quarantine flags)
    - lookup(query: EpisodicQuery) -> list[EpisodicHit]
    - insert(recipe: Recipe, embedding: list[float], source_text: str)
    - update_metadata(recipe_id: str, success: bool)

    Scaling notes:
    - Phase 4: IndexFlatL2 (linear search), ~100k vectors @ <100MB
    - Phase 5+: IndexIVFPQ for 1M+ vectors per faiss-cpu docs

    Architecture reference:
    ~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md
    (Section: Episodic Memory, Lines ~L3400-L3450)
    """

    def __init__(self, faiss_path: Optional[str] = None) -> None:
        """Initialize episodic memory (stub).

        faiss_path: optional override for FAISS index location (default ~/.cua/episodic.faiss)
        """
        self.faiss_path = faiss_path or "~/.cua/episodic.faiss"

    async def lookup(
        self,
        query: EpisodicQuery,
    ) -> list[EpisodicHit]:
        """Stub: returns empty list. Impl in Wave 4 does FAISS nearest-neighbor search."""
        return []

    async def insert(
        self,
        recipe: Recipe,
        embedding: list[float],
        source_text: str,
    ) -> None:
        """Stub: no-op. Impl in Wave 4 adds recipe to FAISS index."""
        pass

    async def update_metadata(
        self,
        recipe_id: str,
        success: bool,
    ) -> None:
        """Stub: no-op. Impl in Wave 4 increments success/failure counters."""
        pass
