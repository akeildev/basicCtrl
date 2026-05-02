"""Embedder — sentence-transformers wrapper for episodic memory writes/reads.

Lazy loads `all-MiniLM-L6-v2` (384-dim) on first encode call. The model
download is ~80MB and cached at `~/.cache/huggingface/`. Subsequent
encodes are <10ms per string on Apple Silicon CPU.
"""
from __future__ import annotations

from typing import Optional, Sequence

import structlog

log = structlog.get_logger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder:
    """Lazy sentence-transformers wrapper.

    The model is constructed on first `.encode(...)` call so test runs
    that never touch episodic memory don't pay the ~3s import cost.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model: Optional[object] = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer

        log.info("embedder.loading", model=self.model_name)
        self._model = SentenceTransformer(self.model_name)
        log.info("embedder.loaded", model=self.model_name)

    def encode(self, text: str) -> list[float]:
        """Return a 384-dim float vector for `text`."""
        self._ensure_loaded()
        # SentenceTransformer.encode returns a numpy.ndarray
        vec = self._model.encode([text], normalize_embeddings=True)[0]  # type: ignore[union-attr]
        return [float(x) for x in vec]

    def encode_many(self, texts: Sequence[str]) -> list[list[float]]:
        self._ensure_loaded()
        arr = self._model.encode(list(texts), normalize_embeddings=True)  # type: ignore[union-attr]
        return [[float(x) for x in row] for row in arr]


def task_source_text(
    app_bundle_id: str, task_label: str, observed_action_summary: str = ""
) -> str:
    """Build the canonical embedding source string.

    We embed the same shape on both write (recipe creation) and read
    (planner lookup) so cosine similarity is meaningful. The optional
    observed_action_summary biases the embedding toward the actual
    action sequence when available, but the (app, task_label) pair is
    enough for a coarse hit.
    """
    base = f"app={app_bundle_id} task={task_label}"
    if observed_action_summary:
        return f"{base} :: {observed_action_summary}"
    return base
