"""Top-level verifier entry — wires L0 push + L1 cheap → WeightedVote → HoarePost.

Per ARCHITECTURE.md Pattern 4 ("Cheap-deterministic-first ladder"):
    L0 push → L1 cheap (1-5 ms) → L2 medium (50-200 ms) → L3 LLM (300-800 ms).

Phase 1 wires L0+L1 only. L2 (Plan 06) and L3 (Plan 06 stub) are escalation
paths the caller (Plan 06) takes when ``confidence < L3_ESCALATE_THRESHOLD``.

Per CLAUDE.md hard rule: "Always use deterministic ensemble first
(L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30."

Per success criterion 4: "L0 push + L1 cheap diff verifies a click in <50 ms
with no AX subtree walk." This module is the heart of that claim:

    L0 push events stream while the action is firing (latency 0).
    L1 cheap diff sub-checks run in parallel (~10-20 ms).
    Both layers run concurrently via ``anyio.create_task_group``.
    WeightedVote.aggregate() with present-signal renormalization picks a
    confidence in [0.0, 1.0]. ≥0.50 -> VERIFIED -> HoarePost(verified=True).
"""
from __future__ import annotations

import time
from typing import Any, Optional

import anyio
import structlog

from cua_overlay.state.causal_dag import ActionCanonical, HoarePost
from cua_overlay.state.graph import UIElement
from cua_overlay.verifier.ensemble.l0_push import L0Push
from cua_overlay.verifier.ensemble.l1_cheap import L1Cheap, L1Snapshot
from cua_overlay.verifier.ensemble.weighted_vote import (
    L3_ESCALATE_THRESHOLD,
    VERIFIED_THRESHOLD,
    WeightedVote,
)


class Aggregator:
    """Top-level verifier entry. Wires L0 push + L1 cheap → WeightedVote → HoarePost.

    Per ARCHITECTURE.md Pattern 4 ("Cheap-deterministic-first ladder"):

    * L0 push events (drain AXObserverManager + NSWorkspace + kqueue futures).
    * L1 cheap diff (CGWindowList + NSPasteboard.changeCount + ROI dHash).
    * Both run IN PARALLEL via ``anyio.create_task_group``.
    * Confidence is computed via ``WeightedVote.aggregate(action_class, signals)``.
    * Result is a ``HoarePost`` whose ``verified`` flag matches
      ``confidence >= VERIFIED_THRESHOLD`` (0.50).
    * Caller (Plan 06) escalates to L2/L3 when ``confidence < L3_ESCALATE_THRESHOLD``
      (0.30).

    Public surface:
        agg = Aggregator(l0, l1, vote)
        # caller has already called manager.expect(...) BEFORE firing
        # caller fires action via translator/channel
        post = await agg.verify(action, target, notifs, before_l1)
    """

    def __init__(self, l0: L0Push, l1: L1Cheap, vote: WeightedVote) -> None:
        self._l0 = l0
        self._l1 = l1
        self._vote = vote
        self._log = structlog.get_logger()

    async def verify(
        self,
        action: ActionCanonical,
        target: UIElement,
        notifs: list[str],
        before_l1: L1Snapshot,
        ax_element: Any = None,
        timeout_ms: int = 50,
    ) -> HoarePost:
        """Run L0 + L1 in parallel; aggregate via WeightedVote; return HoarePost.

        Caller MUST have called ``axmgr.expect()`` (via Plan 04 AXObserverManager)
        BEFORE firing the action. This ``verify()`` is called AFTER firing.

        Args:
            action: The ActionCanonical that just fired. ``action.action_type``
                drives weight selection in WeightedVote (e.g. "click", "type",
                "scroll", "set_value").
            target: UIElement we operated on. ``target.composite_key`` flows
                into ``HoarePost.target_key``.
            notifs: AX notifications passed to L0Push.collect.
            before_l1: pre-action L1Snapshot captured by caller via
                ``await l1.snapshot(target)`` BEFORE the action fired.
            ax_element: opaque AXUIElement ref handed through to L0Push.
            timeout_ms: budget for L0 collect (default 50 ms — the <50 ms
                claim from ROADMAP success criterion 4).

        Returns:
            HoarePost with ``verified == (confidence >= 0.50)``,
            ``tier_signals = {"L0": <max ax.* signal>, "L1": <max l1.* signal>,
            "L2": None, "L3": None}``.
        """
        t_start = time.monotonic()
        l0_signals: dict[str, float] = {}
        l1_signals: dict[str, float] = {}

        async with anyio.create_task_group() as tg:
            async def _l0() -> None:
                nonlocal l0_signals
                l0_signals = await self._l0.collect(
                    target=target,
                    notifs=notifs,
                    action_id=action.id,
                    timeout_ms=timeout_ms,
                    ax_element=ax_element,
                )

            async def _l1() -> None:
                nonlocal l1_signals
                l1_signals = await self._l1.run(target=target, before=before_l1)

            tg.start_soon(_l0)
            tg.start_soon(_l1)

        # Merge signals — L0 keys all start with "ax.", L1 keys all with "l1.";
        # collisions are impossible by construction.
        merged: dict[str, float] = {**l0_signals, **l1_signals}
        confidence = self._vote.aggregate(action.action_type, merged)
        verified = confidence >= VERIFIED_THRESHOLD

        # Per-tier sub-confidence bookkeeping. None means the layer didn't run
        # (no signals arrived) — Plan 06 fills L2/L3 when escalation runs.
        tier_signals: dict[str, Optional[float]] = {
            "L0": self._signal_max(l0_signals, prefix="ax."),
            "L1": self._signal_max(l1_signals, prefix="l1."),
            "L2": None,  # Plan 06 fills if escalation is needed
            "L3": None,  # Plan 06 stub
        }

        elapsed_ms = (time.monotonic() - t_start) * 1000.0
        self._log.info(
            "verifier.aggregated",
            action_id=action.id,
            action_type=action.action_type,
            target_key=target.composite_key,
            confidence=confidence,
            verified=verified,
            escalate_l3=confidence < L3_ESCALATE_THRESHOLD,
            elapsed_ms=elapsed_ms,
            tier_signals=tier_signals,
        )

        return HoarePost(
            target_key=target.composite_key,
            confidence=confidence,
            tier_signals=tier_signals,
            verified=verified,
            healed_to=None,
            timestamp_ns=time.monotonic_ns(),
        )

    @staticmethod
    def _signal_max(signals: dict[str, float], prefix: str) -> Optional[float]:
        """Return max(signal_value) over keys starting with ``prefix``, or None."""
        filtered = [v for k, v in signals.items() if k.startswith(prefix)]
        return max(filtered) if filtered else None
