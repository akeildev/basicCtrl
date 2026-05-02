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

from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field
import structlog

if TYPE_CHECKING:
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

    recipe: Any  # Recipe (forward ref; imported at runtime via episodic_delayed_init)
    similarity: float = Field(..., ge=0.0, le=1.0)
    embedding_source_text: str
    success_count: int = 0
    failure_count: int = 0
    quarantined: bool = False


class EpisodicMemory:
    """Per D-18: FAISS local vector store wrapper for episodic recipe retrieval.

    D-18..D-21: Local FAISS IndexFlatL2 with (app_bundle_id, task_class, state_fingerprint) keys.
    - IndexFlatL2 index from faiss-cpu 1.13.2 (384-dim for sentence-transformers)
    - Local file at ~/.cua/episodic.faiss
    - Metadata sidecar JSON (success_count, failure_count, quarantine flags)
    - lookup(query: EpisodicQuery) -> list[EpisodicHit] with similarity > 0.85
    - index_recipe(recipe, app_bundle_id, task_class, state_fingerprint)
    - mark_recipe_success/failure for quarantine tracking (D-19)

    Scaling notes:
    - Phase 4: IndexFlatL2 (linear search), ~100k vectors @ <100MB
    - Phase 5+: IndexIVFPQ for 1M+ vectors per faiss-cpu docs

    Architecture reference:
    ~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md
    (Section: Episodic Memory, Lines ~L3400-L3450)
    """

    def __init__(
        self,
        faiss_path: Optional[str] = None,
        embedding_dim: int = 384,
    ) -> None:
        """Initialize episodic memory with FAISS backend.

        Args:
            faiss_path: optional override for FAISS index location (default ~/.cua/episodic.faiss)
            embedding_dim: dimension of embedding space (default 384 for sentence-transformers)
        """
        import json
        from pathlib import Path

        self.faiss_path = Path(faiss_path or "~/.cua/episodic.faiss").expanduser()
        self.embedding_dim = embedding_dim
        self.metadata_path = self.faiss_path.parent / f"{self.faiss_path.stem}_metadata.json"

        # Initialize or load FAISS index
        self._index = None
        self._metadata = {}  # Mapping from FAISS row index → recipe metadata
        self._row_to_key = {}  # Mapping from FAISS row index → (app, task_class, state_fp)

        # Lazy import FAISS on first use
        self._faiss_loaded = False

    def _load_faiss(self):
        """Lazy-load FAISS library."""
        if self._faiss_loaded:
            return

        import faiss

        self._faiss_loaded = True

        # Load or create index
        if self.faiss_path.exists():
            self._index = faiss.read_index(str(self.faiss_path))
        else:
            # Create new IndexFlatL2 (384-dim for all-MiniLM-L6-v2)
            self._index = faiss.IndexFlatL2(self.embedding_dim)

        # Load metadata if exists
        if self.metadata_path.exists():
            import json

            with open(self.metadata_path) as f:
                self._metadata = json.load(f)

    def _save_index(self):
        """Persist FAISS index to disk."""
        import faiss

        if self._index is None:
            return

        self.faiss_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.faiss_path))

    def _save_metadata(self):
        """Persist metadata sidecar to JSON."""
        import json

        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metadata_path, "w") as f:
            json.dump(self._metadata, f, indent=2)

    async def index_recipe(
        self,
        recipe: Any,
        app_bundle_id: str,
        task_class: str,
        state_fingerprint: str,
        embedding: list[float],
        source_text: str,
    ) -> None:
        """Index recipe into FAISS with (app, task_class, state_fp) key.

        Per D-19: Store recipe with embedding, metadata (success_count=0, failure_count=0, quarantined=False).

        Args:
            recipe: Recipe object
            app_bundle_id: Target app (e.g., "com.google.Chrome")
            task_class: Task category (e.g., "web_search")
            state_fingerprint: SHA-256 of app state at recording time
            embedding: 384-dim vector from sentence-transformers
            source_text: Original text used for embedding (for re-embedding if model changes)
        """
        import numpy as np

        log = structlog.get_logger()
        self._load_faiss()

        # Add embedding to FAISS index
        embedding_array = np.array([embedding], dtype=np.float32)
        row_idx = self._index.ntotal
        self._index.add(embedding_array)

        # Store metadata
        composite_key = f"{app_bundle_id}:{task_class}:{state_fingerprint}"
        self._metadata[str(row_idx)] = {
            "recipe_name": getattr(recipe, "name", "unknown"),
            "app_bundle_id": app_bundle_id,
            "task_class": task_class,
            "state_fingerprint": state_fingerprint,
            "embedding_source_text": source_text,
            "success_count": 0,
            "failure_count": 0,
            "quarantined": False,
            "composite_key": composite_key,
            "recipe": recipe.model_dump() if hasattr(recipe, "model_dump") else None,
        }

        self._row_to_key[row_idx] = composite_key

        # Persist to disk
        self._save_index()
        self._save_metadata()

        # Emit structured event
        log.info(
            "memory.write",
            app_bundle_id=app_bundle_id,
            task_class=task_class,
            row_idx=row_idx,
            recipe_name=getattr(recipe, "name", "unknown"),
        )

    async def lookup(
        self,
        query: EpisodicQuery,
    ) -> list[EpisodicHit]:
        """Return top-K recipes with similarity > 0.85.

        Per D-20: Called BEFORE planner LLM call. Quarantined recipes surface
        with quarantined=True flag.

        Args:
            query: EpisodicQuery with app_bundle_id, task_class, embedding, top_k

        Returns:
            List of EpisodicHit, sorted by similarity descending
        """
        import numpy as np

        log = structlog.get_logger()
        self._load_faiss()

        # Emit lookup start event
        log.info(
            "memory.lookup",
            app_bundle_id=query.app_bundle_id,
            task_class=query.task_class,
        )

        if self._index is None or self._index.ntotal == 0:
            log.info(
                "memory.miss",
                app_bundle_id=query.app_bundle_id,
                task_class=query.task_class,
                reason="empty_index",
            )
            return []

        # FAISS nearest-neighbor search
        k = query.top_k
        query_embedding = np.array([query.query_embedding], dtype=np.float32)

        # IndexFlatL2 returns (distances, indices)
        # L2 distance is sqrt of (sum of squared differences)
        # Convert to similarity: similarity = 1 / (1 + distance)
        distances, indices = self._index.search(query_embedding, min(k, self._index.ntotal))

        hits = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                # Invalid index from FAISS
                continue

            # Convert L2 distance to similarity
            # L2 distance ~ euclidean; for normalized embeddings, 1 / (1 + dist) approx cosine
            similarity = 1.0 / (1.0 + float(dist))

            # Filter by similarity threshold (D-20)
            if similarity < 0.85:
                continue

            row_idx = int(idx)
            if str(row_idx) not in self._metadata:
                continue

            metadata = self._metadata[str(row_idx)]

            # Reconstruct Recipe object
            recipe = None
            if metadata.get("recipe"):
                from cua_overlay.learning import Recipe

                try:
                    recipe = Recipe(**metadata["recipe"])
                except Exception:
                    # Fallback if recipe dict is malformed
                    recipe = None

            if recipe:
                hit = EpisodicHit(
                    recipe=recipe,
                    similarity=similarity,
                    embedding_source_text=metadata.get("embedding_source_text", ""),
                    success_count=metadata.get("success_count", 0),
                    failure_count=metadata.get("failure_count", 0),
                    quarantined=metadata.get("quarantined", False),
                )
                hits.append(hit)

        # Emit hit or miss event
        if hits:
            log.info(
                "memory.hit",
                app_bundle_id=query.app_bundle_id,
                task_class=query.task_class,
                num_hits=len(hits),
                top_similarity=hits[0].similarity if hits else None,
            )
        else:
            log.info(
                "memory.miss",
                app_bundle_id=query.app_bundle_id,
                task_class=query.task_class,
                reason="no_matches_above_threshold",
            )

        return hits

    def mark_recipe_success(self, row_idx: int) -> None:
        """Increment success_count for recipe at row_idx.

        Per D-19: Track empirical success on replay.
        """
        self._load_faiss()

        if str(row_idx) in self._metadata:
            self._metadata[str(row_idx)]["success_count"] += 1
            self._save_metadata()

    def mark_recipe_failure(self, row_idx: int) -> None:
        """Increment failure_count; quarantine if > 2.

        Per D-19: On >2 failures, mark quarantined=True (recipe surfaces as low-confidence only).
        """
        log = structlog.get_logger()
        self._load_faiss()

        if str(row_idx) in self._metadata:
            self._metadata[str(row_idx)]["failure_count"] += 1

            # Quarantine on >2 failures (D-19)
            if self._metadata[str(row_idx)]["failure_count"] > 2:
                self._metadata[str(row_idx)]["quarantined"] = True
                log.warning(
                    "memory.quarantine",
                    row_idx=row_idx,
                    recipe_name=self._metadata[str(row_idx)].get("recipe_name", "unknown"),
                    failure_count=self._metadata[str(row_idx)]["failure_count"],
                )
            else:
                log.info(
                    "memory.failure_recorded",
                    row_idx=row_idx,
                    failure_count=self._metadata[str(row_idx)]["failure_count"],
                )

            self._save_metadata()

    async def insert(
        self,
        recipe: Any,
        embedding: list[float],
        source_text: str,
    ) -> None:
        """Legacy stub method (for backward compatibility)."""
        # This is kept for API compatibility but index_recipe is the main method
        pass

    async def update_metadata(
        self,
        recipe_id: str,
        success: bool,
    ) -> None:
        """Legacy stub method (for backward compatibility)."""
        # This is kept for API compatibility but mark_recipe_success/failure are the main methods
        pass
