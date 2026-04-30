"""Tests for recovery classifier.

Covers all 6 FailureClass routes and dispatch table.
"""
from __future__ import annotations

import pytest

from cua_overlay.recovery.classifier import (
    FailureClass,
    FailureClassifier,
    FAILURE_CLASS_TO_BRANCHES,
)
from cua_overlay.state.causal_dag import HoarePost


@pytest.fixture
def classifier() -> FailureClassifier:
    """Instantiate classifier for tests."""
    return FailureClassifier()


@pytest.fixture
def hoare_post_fixture() -> HoarePost:
    """Create a default HoarePost for testing."""
    return HoarePost(
        target_key="test_target",
        confidence=0.5,
        tier_signals={"L0": None, "L1": None, "L2": None, "L3": None},
        verified=True,
        timestamp_ns=1000000000,
    )


def test_failure_class_enum_has_6_variants() -> None:
    """Verify FailureClass enum has exactly 6 members."""
    members = list(FailureClass)
    assert len(members) == 6
    names = {m.name for m in members}
    expected = {"PERCEPTUAL", "COGNITIVE", "ACTUATION", "ENVIRONMENTAL", "RESOURCE", "LOOP"}
    assert names == expected


def test_classify_perceptual_low_confidence(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Test classification of very low confidence → PERCEPTUAL."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.05,
        "last_error": "",
        "previous_failures_count": 0,
    }
    fc, conf_pct = classifier.classify(ctx)
    assert fc == FailureClass.PERCEPTUAL
    assert 0 <= conf_pct <= 100


def test_classify_actuation_ax_error(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Test classification of AX error → ACTUATION."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.2,
        "last_error": "kAXErrorCannotComplete",
        "previous_failures_count": 0,
    }
    fc, conf_pct = classifier.classify(ctx)
    assert fc == FailureClass.ACTUATION


def test_classify_environmental_cdp_closed(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Test classification of CDP error → ENVIRONMENTAL."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.4,
        "last_error": "cdp ws closed",
        "previous_failures_count": 0,
    }
    fc, conf_pct = classifier.classify(ctx)
    assert fc == FailureClass.ENVIRONMENTAL


def test_classify_resource_timeout(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Test classification of timeout → RESOURCE."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.4,
        "last_error": "timed out",
        "previous_failures_count": 0,
    }
    fc, conf_pct = classifier.classify(ctx)
    assert fc == FailureClass.RESOURCE


def test_classify_cognitive_unexpected_state(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Test classification of unexpected state → COGNITIVE."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.6,
        "last_error": "unexpected state change",
        "previous_failures_count": 0,
    }
    fc, conf_pct = classifier.classify(ctx)
    assert fc == FailureClass.COGNITIVE


def test_classify_loop_repeated_failures(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Test classification of repeated failures → LOOP."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.75,
        "last_error": "still failing",
        "previous_failures_count": 3,
    }
    fc, conf_pct = classifier.classify(ctx)
    assert fc == FailureClass.LOOP


def test_branch_dispatch_table_complete() -> None:
    """Verify dispatch table has all 6 FailureClass keys with non-empty lists."""
    assert len(FAILURE_CLASS_TO_BRANCHES) == 6
    for fc in FailureClass:
        assert fc in FAILURE_CLASS_TO_BRANCHES
        branches = FAILURE_CLASS_TO_BRANCHES[fc]
        assert isinstance(branches, list)
        assert len(branches) > 0


def test_classify_returns_tuple_with_confidence(
    classifier: FailureClassifier, hoare_post_fixture: HoarePost
) -> None:
    """Verify classify() returns (FailureClass, int) tuple."""
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "target1",
        "hoare_post": hoare_post_fixture,
        "confidence": 0.5,
        "last_error": "test",
        "previous_failures_count": 0,
    }
    result = classifier.classify(ctx)
    assert isinstance(result, tuple)
    assert len(result) == 2
    fc, conf_pct = result
    assert isinstance(fc, FailureClass)
    assert isinstance(conf_pct, int)
    assert 0 <= conf_pct <= 100
