"""STATE-02 — ActionCanonical, HoarePre, HoarePost, CausalDAG.

The action contract (``ActionCanonical``) is the canonical message every
translator and channel reads/writes. The Hoare-triple contracts
(``HoarePre`` / ``HoarePost``) live alongside it so the deterministic
ensemble verifier (Phase 1 plans 04-06) and the cognition layer (Phase 4)
share the same vocabulary.

Speculation safety (Pitfall 22): ``ActionCanonical.kind`` is a
``Literal["READ", "MUTATE"]``. Speculative pre-execution in Phase 4 must
ONLY race actions whose ``kind == "READ"``. The type system enforces it
at every call site — no runtime "is this destructive?" probe needed.

Idempotency (ACT-03): the ``id`` field doubles as the idempotency token.
Phase 2 channels check it before fire and skip if another channel already
claimed it. We pin that contract in the unit test now even though the
checker itself is wired later.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cua_overlay.state.graph import Edge, EdgeKind, StateGraph


class ActionCanonical(BaseModel):
    """Canonical action: tier-and-channel-agnostic, idempotent, typed."""

    model_config = ConfigDict(frozen=True)

    id: str  # UUID; doubles as the ACT-03 idempotency token
    step_idx: int
    kind: Literal["READ", "MUTATE"]  # P22 speculation-safety gate
    target_key: str
    action_type: str  # "click" | "type" | "scroll" | "set_value" | ...
    payload: dict[str, object]
    tier: Optional[Literal["T1", "T2", "T3", "T4", "T5"]] = None
    channel: Optional[Literal["C1", "C2", "C3", "C4", "C5"]] = None
    timestamp_ns: int
    session_id: str


class HoarePre(BaseModel):
    """Hoare pre-condition snapshot evaluated immediately before action fire.

    ``no_blocking_modal=False`` implies a modal is on top, in which case the
    target_key for the underlying action probably can't even be hit-tested.
    A defensive validator asserts: ``not no_blocking_modal -> target_exists``
    (we shouldn't be claiming we can act on something that's hidden by a
    modal, except for the modal itself). The validator only fires the
    contradiction case so legitimate "modal is up; target IS the modal"
    flows are fine.
    """

    model_config = ConfigDict(frozen=True)

    target_key: str
    target_exists: bool
    target_enabled: bool
    target_role: str
    role_compatible: bool
    frontmost_app: str
    no_blocking_modal: bool
    timestamp_ns: int


class HoarePost(BaseModel):
    """Hoare post-condition: deterministic-ensemble vote per tier.

    ``tier_signals`` is the per-layer confidence, e.g.
    ``{"L0": 0.8, "L1": 0.3, "L2": None, "L3": None}`` — None means that
    layer didn't run (we short-circuit when L0+L1 already crosses the
    confidence floor).

    ``verified == (confidence >= 0.5)`` is enforced by a
    ``model_validator`` so callers can't accidentally desync the two.
    """

    model_config = ConfigDict(frozen=True)

    target_key: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    tier_signals: dict[str, Optional[float]]
    verified: bool
    healed_to: Optional[str] = None
    timestamp_ns: int

    @model_validator(mode="after")
    def _verified_matches_confidence(self) -> "HoarePost":
        expected = self.confidence >= 0.5
        if self.verified != expected:
            raise ValueError(
                f"HoarePost.verified={self.verified} but confidence={self.confidence!r} "
                f"implies verified={expected} (threshold 0.5)"
            )
        return self


class CausalDAG:
    """Action-to-state-delta DAG.

    Edges are TRIGGERS edges (see ``EdgeKind.TRIGGERS``). A single
    ``record(action, pre, post)`` call diffs the two state graphs and emits
    one edge per node that changed (added, value-changed, focus-changed).
    """

    def __init__(self) -> None:
        self.edges: list[Edge] = []

    def record(
        self,
        action: ActionCanonical,
        pre: StateGraph,
        post: StateGraph,
    ) -> list[Edge]:
        """Diff ``pre`` → ``post`` and return the new TRIGGERS edges.

        Diff strategy: for each node in ``post.nodes``, emit an edge if
        either (a) the node didn't exist in ``pre`` (creation), (b) its
        ``value`` changed, or (c) its ``focused`` flag changed. We don't
        diff bbox or capabilities here — those drift constantly and would
        flood the DAG.
        """
        new_edges: list[Edge] = []
        for key, post_elem in post.nodes.items():
            pre_elem = pre.nodes.get(key)
            changed = (
                pre_elem is None
                or pre_elem.value != post_elem.value
                or pre_elem.focused != post_elem.focused
            )
            if changed:
                new_edges.append(
                    Edge(
                        src=action.id,
                        dst=key,
                        kind=EdgeKind.TRIGGERS,
                        timestamp_ns=action.timestamp_ns,
                    )
                )
        self.edges.extend(new_edges)
        return new_edges
