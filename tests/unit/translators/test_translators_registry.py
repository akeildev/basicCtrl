"""TRANS-01..05 — TranslatorRegistry registration + priority selection."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from basicctrl.state.graph import Bbox, UIElement
from basicctrl.translators import (
    TargetSpec,
    Translator,
    TranslatorRegistry,
    TranslatorTarget,
)


class _FakeT1:
    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T1"

    async def resolve(self, bundle_id, pid, target_spec) -> Optional[TranslatorTarget]:
        return None

    async def validate(self, target) -> bool:
        return True


class _FakeT4:
    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T4"

    async def resolve(self, bundle_id, pid, target_spec) -> Optional[TranslatorTarget]:
        return None

    async def validate(self, target) -> bool:
        return True


def test_register_and_get() -> None:
    reg = TranslatorRegistry()
    t1 = _FakeT1()
    reg.register(t1)
    assert reg.get("T1") is t1
    assert reg.get("T9") is None


def test_select_for_priority_returns_in_order() -> None:
    reg = TranslatorRegistry()
    t1, t4 = _FakeT1(), _FakeT4()
    reg.register(t1)
    reg.register(t4)
    selected = reg.select_for_priority(["T4", "T1"])
    assert [t.tier for t in selected] == ["T4", "T1"]


def test_select_for_priority_skips_unregistered() -> None:
    reg = TranslatorRegistry()
    reg.register(_FakeT1())
    selected = reg.select_for_priority(["T2", "T1", "T5"])
    # Only T1 registered.
    assert [t.tier for t in selected] == ["T1"]


def test_register_replaces_idempotent() -> None:
    reg = TranslatorRegistry()
    a, b = _FakeT1(), _FakeT1()
    reg.register(a)
    reg.register(b)
    assert reg.get("T1") is b


def test_translator_target_carries_optional_handles() -> None:
    """TranslatorTarget Pydantic model carries optional per-tier handles."""
    elem = UIElement(
        role="AXButton",
        role_path="AXApplication/AXButton[5]",
        label="5",
        bbox=Bbox(x=10, y=20, w=30, h=40),
        pid=1234,
        bundle_id="com.apple.calculator",
        window_id=0,
        discovered_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    t = TranslatorTarget(
        element=elem,
        ax_element=object(),
        cdp_node_id=42,
        cdp_session_id="sess-1",
        as_target_spec='tell application "Pages" to ...',
        grounded_bbox=Bbox(x=0, y=0, w=100, h=100),
        extras={"pre_phash": "abcdef"},
    )
    assert t.element.label == "5"
    assert t.cdp_node_id == 42
    assert t.cdp_session_id == "sess-1"
    assert t.extras["pre_phash"] == "abcdef"
