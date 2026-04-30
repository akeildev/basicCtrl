"""Learning recorder — CGEvent tap + recipe synthesis + episodic memory integration.

Per Phase 4 D-11..D-17: continuous learning from observed user actions,
coalesced keystroke recording, and automatic Recipe JSON synthesis.

Submodules:
  - schemas.py — ObservedAction, Recipe, RecipeStep, RecipeParam, RecipePrecondition
  - recorder.py (future) — CGEvent tap consumer, JSONL → ObservedAction conversion
  - recipe_synth.py (future) — sequence of ObservedAction → Recipe JSON
  - coalesce.py (future) — keystroke coalescing via CFRunLoopTimer (0.5s)

All frozen=True per Phase 1-3 precedent.
"""
from __future__ import annotations

from .schemas import (
    ObservedAction,
    Recipe,
    RecipeParam,
    RecipePrecondition,
    RecipeStep,
)

__all__ = [
    "ObservedAction",
    "Recipe",
    "RecipeParam",
    "RecipePrecondition",
    "RecipeStep",
]
