"""TRANS-01 — T1 AX translator unit tests with mocked AX surface.

Wave-2 plan 02-05: T1AXTranslator wraps Phase 1 ax/* (TokenBucket, walker
primitives, AXObserver), implements Translator Protocol with tier='T1'.

These tests use mocks for the AX surface so they run on any host (no
Calculator, no TCC). Real Calculator integration lives in
tests/integration/test_t1_calculator.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from basicctrl.ax.rate_limit import TokenBucket
from basicctrl.state.graph import Bbox, UIElement
from basicctrl.translators.base import TargetSpec, TranslatorTarget
from basicctrl.translators.t1_ax import T1AXTranslator


def _fake_uielement(label: str, role: str = "AXButton", pid: int = 1234) -> UIElement:
    return UIElement(
        role=role,
        role_path=f"AXApplication/{role}[1]",
        label=label,
        bbox=Bbox(x=10, y=20, w=30, h=40),
        pid=pid,
        bundle_id="com.apple.calculator",
        window_id=0,
        discovered_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )


def test_tier_is_T1() -> None:
    """T1AXTranslator declares tier='T1' (Translator Protocol contract)."""
    t = T1AXTranslator()
    assert t.tier == "T1"


async def test_resolve_returns_none_on_label_miss() -> None:
    """resolve returns None when no walked node matches the requested label."""
    t = T1AXTranslator()
    elem_other = _fake_uielement("OtherButton")
    fake_walk = [(elem_other, object())]  # list[(UIElement, ax_ref)]
    with patch(
        "basicctrl.ax.window_manager.ensure_real_window",
        return_value=object(),
    ):
        with patch.object(t, "_get_app_element", return_value=object()):
            with patch.object(t, "_walk_with_refs", return_value=fake_walk):
                target = await t.resolve(
                    "com.apple.calculator", 1234, TargetSpec(label="5")
                )
    assert target is None


async def test_resolve_matches_by_label() -> None:
    """resolve returns TranslatorTarget when walker yields a label-matching node."""
    t = T1AXTranslator()
    elem = _fake_uielement("5")
    ax_ref = object()
    fake_walk = [(elem, ax_ref)]
    with patch(
        "basicctrl.ax.window_manager.ensure_real_window",
        return_value=object(),
    ):
        with patch.object(t, "_get_app_element", return_value=object()):
            with patch.object(t, "_walk_with_refs", return_value=fake_walk):
                with patch.object(t, "validate", return_value=True):
                    target = await t.resolve(
                        "com.apple.calculator", 1234, TargetSpec(label="5")
                    )
    assert target is not None
    assert target.element.label == "5"
    assert target.ax_element is ax_ref


async def test_resolve_returns_none_when_no_real_windows() -> None:
    """Phase H: pid with no visible windows short-circuits before walk."""
    t = T1AXTranslator()
    with patch(
        "basicctrl.ax.window_manager.ensure_real_window",
        return_value=None,
    ):
        target = await t.resolve(
            "com.apple.calculator", 1234, TargetSpec(label="5")
        )
    assert target is None


async def test_validate_rate_limited_returns_false() -> None:
    """P2 mitigation: when bucket is exhausted, validate returns False (fail-open)."""
    bucket = TokenBucket(rate_per_sec=0.0001, capacity=0)
    # Force the bucket to deny by pre-seeding zero tokens for the pid.
    bucket.tokens[1234] = 0.0
    import time as _time
    bucket.last_refill[1234] = _time.monotonic()
    t = T1AXTranslator(rate_limiter=bucket)
    target = TranslatorTarget(
        element=_fake_uielement("5"), ax_element=object()
    )
    assert await t.validate(target) is False


async def test_validate_axrole_returns_true_on_success() -> None:
    """validate returns True when AXUIElementCopyAttributeValue succeeds (err=0)."""
    t = T1AXTranslator()
    target = TranslatorTarget(
        element=_fake_uielement("5"), ax_element=object()
    )
    fake_module = SimpleNamespace(
        AXUIElementCopyAttributeValue=lambda elem, attr, _: (0, "AXButton")
    )
    with patch.dict("sys.modules", {"HIServices": fake_module}):
        assert await t.validate(target) is True


async def test_validate_axrole_returns_false_on_invalid_element() -> None:
    """P28 stale-ref mitigation: validate returns False on kAXErrorInvalidUIElement."""
    t = T1AXTranslator()
    target = TranslatorTarget(
        element=_fake_uielement("5"), ax_element=object()
    )
    # kAXErrorInvalidUIElement = -25202 — non-zero.
    fake_module = SimpleNamespace(
        AXUIElementCopyAttributeValue=lambda elem, attr, _: (-25202, None)
    )
    with patch.dict("sys.modules", {"HIServices": fake_module}):
        assert await t.validate(target) is False
