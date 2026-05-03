"""Failure classification logic for recovery routing.

Per CONTEXT.md D-01, D-02: 6-class enum FailureClass with decision tree
routing to recovery branches B1-B5. Each failure is analyzed by confidence
level + error pattern to determine the most likely root cause and thus which
recovery branch to attempt first.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Tuple, TypedDict

from basicctrl.state.causal_dag import HoarePost


class FailureClass(str, Enum):
    """Six-class failure taxonomy for recovery routing."""

    PERCEPTUAL = "PERCEPTUAL"  # screen changed unexpectedly
    COGNITIVE = "COGNITIVE"  # action didn't make logical sense
    ACTUATION = "ACTUATION"  # OS rejected action (kAXError, disabled, hidden)
    ENVIRONMENTAL = "ENVIRONMENTAL"  # external state changed
    RESOURCE = "RESOURCE"  # out of capacity (AX saturation, memory)
    LOOP = "LOOP"  # repeated failures on same target


class FailureCtx(TypedDict):
    """Context for classifying a failure.

    Fields:
      - bundle_id: target app bundle identifier
      - target_key: composite locator key from Phase 1
      - hoare_post: HoarePost result from RaceOrchestrator
      - confidence: verifier confidence 0.0-1.0
      - last_error: error message from verifier/translator
      - previous_failures_count: count of prior failures on this target
    """

    bundle_id: str
    target_key: str
    hoare_post: HoarePost
    confidence: float
    last_error: str
    previous_failures_count: int


# Branch dispatch table: each FailureClass -> list of branch IDs to attempt
FAILURE_CLASS_TO_BRANCHES = {
    FailureClass.PERCEPTUAL: ["B1_RESCROLL", "B2_OCR_REGROUND", "B4_PLANNER"],
    FailureClass.COGNITIVE: ["B3_WORLD_REPLAN", "B4_PLANNER"],
    FailureClass.ACTUATION: ["B1_RESCROLL", "B2_OCR_REGROUND", "B5_APPLESCRIPT"],
    FailureClass.ENVIRONMENTAL: ["B5_APPLESCRIPT", "B4_PLANNER"],
    FailureClass.RESOURCE: ["B2_OCR_REGROUND", "B1_RESCROLL"],
    FailureClass.LOOP: ["B5_APPLESCRIPT"],  # last resort
}


class FailureClassifier:
    """Classify verifier failures into 6 classes for recovery routing."""

    def classify(self, ctx: FailureCtx) -> Tuple[FailureClass, int]:
        """Classify a failure and return (class, confidence_pct).

        Decision tree based on confidence + error patterns:
          - confidence < 0.10 → PERCEPTUAL
          - confidence 0.10-0.30 + "kAXErrorCannotComplete" → ACTUATION
          - confidence 0.30-0.50 + "cdp ws closed" → ENVIRONMENTAL
          - confidence 0.30-0.50 + "timed out" → RESOURCE
          - confidence 0.50-0.70 + "unexpected state" → COGNITIVE
          - confidence > 0.70 + previous_failures_count >= 3 → LOOP
          - default: PERCEPTUAL

        Args:
            ctx: FailureCtx with bundle_id, target_key, hoare_post, confidence,
                 last_error, previous_failures_count

        Returns:
            Tuple[FailureClass, confidence_pct] where confidence_pct is 0-100
            reflecting decisiveness of routing.
        """
        conf = ctx["confidence"]
        error = ctx["last_error"].lower()
        prev_count = ctx["previous_failures_count"]

        # Perceptual: very low confidence or no clear pattern
        if conf < 0.10:
            return (FailureClass.PERCEPTUAL, int(100 * (1 - conf)))

        # Actuation: low-mid confidence + AX system error
        if 0.10 <= conf < 0.30 and "kaxerror" in error:
            return (FailureClass.ACTUATION, 75)

        # Environmental: mid confidence + network/CDP error
        if 0.30 <= conf < 0.50 and "cdp ws closed" in error:
            return (FailureClass.ENVIRONMENTAL, 70)

        # Resource: mid confidence + timeout
        if 0.30 <= conf < 0.50 and "timed out" in error:
            return (FailureClass.RESOURCE, 65)

        # Cognitive: higher confidence + unexpected state pattern
        if 0.50 <= conf < 0.70 and "unexpected state" in error:
            return (FailureClass.COGNITIVE, 60)

        # Loop: high confidence + repeated failures
        if conf > 0.70 and prev_count >= 3:
            return (FailureClass.LOOP, 80)

        # Default to perceptual (catch-all)
        return (FailureClass.PERCEPTUAL, 40)
