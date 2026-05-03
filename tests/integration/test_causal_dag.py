"""STATE-02 — ActionCanonical, HoarePre, HoarePost, CausalDAG.

Marked under integration/ to keep it co-located with future tests that probe
real apps (Calculator, etc.) — the contracts and the live verifier will
share fixtures.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from basicctrl.state.causal_dag import ActionCanonical, CausalDAG, HoarePost, HoarePre
from basicctrl.state.graph import (
    Bbox,
    Capability,
    EdgeKind,
    Source,
    StateGraph,
    UIElement,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _button(label: str, *, value: str = "0") -> UIElement:
    return UIElement(
        role="AXButton",
        role_path="AXButton[3]",
        label=label,
        bbox=Bbox(x=0.0, y=0.0, w=10.0, h=10.0),
        value=value,
        capabilities=[Capability.PRESS],
        source=[Source.AX],
        discovered_at=_now(),
        last_seen_at=_now(),
        pid=1,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )


def _action(target: UIElement, kind: str = "MUTATE") -> ActionCanonical:
    return ActionCanonical(
        id=str(uuid.uuid4()),
        step_idx=0,
        kind=kind,  # type: ignore[arg-type]
        target_key=target.composite_key,
        action_type="click",
        payload={"button": "left"},
        timestamp_ns=time.monotonic_ns(),
        session_id="test-session",
    )


def test_actioncanonical_kind_required() -> None:
    """ActionCanonical.kind must be Literal['READ','MUTATE'] — anything else rejected."""
    btn = _button("5")
    with pytest.raises(ValidationError):
        ActionCanonical(
            id=str(uuid.uuid4()),
            step_idx=0,
            kind="WAT",  # type: ignore[arg-type]
            target_key=btn.composite_key,
            action_type="click",
            payload={},
            timestamp_ns=time.monotonic_ns(),
            session_id="s",
        )

    # READ and MUTATE both valid.
    for k in ("READ", "MUTATE"):
        ActionCanonical(
            id=str(uuid.uuid4()),
            step_idx=0,
            kind=k,  # type: ignore[arg-type]
            target_key=btn.composite_key,
            action_type="click",
            payload={},
            timestamp_ns=time.monotonic_ns(),
            session_id="s",
        )


def test_actioncanonical_id_is_idempotency_token() -> None:
    """Two ActionCanonical built with the same id collide on idempotency.

    The actual idempotency check lives in Phase 2; this test pins the
    contract that ``id`` is the canonical token.
    """
    same_id = str(uuid.uuid4())
    btn = _button("5")
    a = ActionCanonical(
        id=same_id,
        step_idx=0,
        kind="MUTATE",
        target_key=btn.composite_key,
        action_type="click",
        payload={"x": 1},
        timestamp_ns=time.monotonic_ns(),
        session_id="s",
    )
    b = ActionCanonical(
        id=same_id,
        step_idx=99,
        kind="READ",
        target_key="some-other-key",
        action_type="screenshot",
        payload={"x": 2},
        timestamp_ns=time.monotonic_ns(),
        session_id="t",
    )

    # Phase-2 contract: dedupe key is a.id == b.id.
    assert a.id == b.id


def test_click_triggers_edge() -> None:
    """A MUTATE action whose post-state diff shows a value change emits a TRIGGERS edge."""
    btn_pre = _button("5", value="0")
    pre = StateGraph()
    pre.upsert(btn_pre)

    btn_post = btn_pre.model_copy(update={"value": "5"})
    post = StateGraph()
    post.upsert(btn_post)

    action = _action(btn_pre)
    dag = CausalDAG()
    new = dag.record(action, pre, post)

    assert len(new) == 1
    edge = new[0]
    assert edge.kind is EdgeKind.TRIGGERS
    assert edge.src == action.id
    assert edge.dst == btn_post.composite_key
    assert dag.edges == new


def test_no_edge_when_state_unchanged() -> None:
    """Identical pre/post graphs produce zero TRIGGERS edges."""
    btn = _button("5", value="0")
    pre = StateGraph()
    pre.upsert(btn)
    post = StateGraph()
    post.upsert(btn)

    action = _action(btn)
    dag = CausalDAG()
    assert dag.record(action, pre, post) == []
    assert dag.edges == []


def test_hoare_pre_post_roundtrip() -> None:
    """HoarePre and HoarePost JSON-roundtrip cleanly."""
    pre = HoarePre(
        target_key="axid:com.apple.Calculator:btn-5",
        target_exists=True,
        target_enabled=True,
        target_role="AXButton",
        role_compatible=True,
        frontmost_app="com.apple.Calculator",
        no_blocking_modal=True,
        timestamp_ns=time.monotonic_ns(),
    )
    raw = pre.model_dump_json()
    parsed = HoarePre.model_validate_json(raw)
    assert parsed == pre

    post = HoarePost(
        target_key=pre.target_key,
        confidence=0.85,
        tier_signals={"L0": 0.8, "L1": 0.3, "L2": None, "L3": None},
        verified=True,
        timestamp_ns=time.monotonic_ns(),
    )
    raw_post = post.model_dump_json()
    parsed_post = HoarePost.model_validate_json(raw_post)
    assert parsed_post == post
    assert parsed_post.verified is True


def test_hoare_post_consistency_validator() -> None:
    """HoarePost rejects (confidence>=0.5, verified=False) and vice versa."""
    with pytest.raises(ValidationError):
        HoarePost(
            target_key="k",
            confidence=0.9,
            tier_signals={"L0": 0.9},
            verified=False,
            timestamp_ns=0,
        )
    with pytest.raises(ValidationError):
        HoarePost(
            target_key="k",
            confidence=0.1,
            tier_signals={"L0": 0.1},
            verified=True,
            timestamp_ns=0,
        )
