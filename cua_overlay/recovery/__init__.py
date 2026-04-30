"""Recovery orchestration after verification failure.

Phase 3 recovery subsystem: classifies failures into 6 classes, dispatches
5 parallel recovery branches, takes first-verified result, emits heal events,
writes back to cassette atomically.

Submodules:
  - classifier.py — 6-class FailureClass enum + dispatch table
  - branches/ — b1_rescroll.py, b2_ocr_reground.py, b3_world_replan_stub.py,
    b4_planner_reqry_stub.py, b5_applescript.py
  - orchestrator.py — RecoveryOrchestrator + BranchOrchestrator +
    first_verified wrapper
  - circuit_breaker.py — per-(bundle_id, target_key) counter, trip on
    3 consecutive failures
  - heal_event.py — HealEvent Pydantic model, emitters
"""

from . import branches
from .branches import B1_Rescroll, B2_OCRRegrounding, B3_WorldReplan, B4_PlannerRequery, B5_AppleScriptFallback
from .circuit_breaker import CircuitBreaker, BreakState
from .classifier import FailureClass, FailureClassifier, FailureCtx, FAILURE_CLASS_TO_BRANCHES
from .heal_event import HealEvent

__all__ = [
    "branches",
    "B1_Rescroll",
    "B2_OCRRegrounding",
    "B3_WorldReplan",
    "B4_PlannerRequery",
    "B5_AppleScriptFallback",
    "BreakState",
    "CircuitBreaker",
    "FailureClass",
    "FailureClassifier",
    "FailureCtx",
    "FAILURE_CLASS_TO_BRANCHES",
    "HealEvent",
]
