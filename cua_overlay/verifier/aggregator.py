"""Top-level verifier entry — wires L0+L1 in parallel, escalates to L2/L3.

Per ARCHITECTURE.md Pattern 4 ("Cheap-deterministic-first ladder"):
    L0 push → L1 cheap (1-5 ms) → L2 medium (50-200 ms) → L3 LLM (300-800 ms).

Plan 06 wires the FULL ladder: L0+L1 first (parallel via anyio task group),
then escalation through L2 (in-band 0.30..0.50) and L3 (below 0.30, raises
in Phase 1).

Per CLAUDE.md hard rule: "Always use deterministic ensemble first
(L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30."

Per success criterion 4: "L0 push + L1 cheap diff verifies a click in
<50 ms with no AX subtree walk." This module preserves that fast path:

    L0 push events stream while the action is firing (latency 0).
    L1 cheap diff sub-checks run in parallel (~10-20 ms).
    Both layers run concurrently via ``anyio.create_task_group``.
    WeightedVote.aggregate() picks a confidence in [0.0, 1.0].
    >= 0.50 → VERIFIED → return early. L2/L3 NOT touched.

Escalation only fires when confidence is below 0.50:

    [0.30, 0.50) → L2 runs (Vision OCR ROI + walker subtree).
                   L2 signals can boost confidence above 0.50.
    < 0.30        → L2 still runs first (deterministic try); if STILL
                   below 0.30, L3 is invoked. Phase 1 L3Stub raises
                   NotImplementedError → aggregator catches, emits a
                   structured 'l3.unavailable_phase1' warning event,
                   returns HoarePost(verified=False).
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
from cua_overlay.verifier.ensemble.l2_medium import L2Medium, L2Snapshot
from cua_overlay.verifier.ensemble.l3_llm import L3Contract
from cua_overlay.verifier.ensemble.weighted_vote import (
    L3_ESCALATE_THRESHOLD,
    VERIFIED_THRESHOLD,
    WeightedVote,
)


class Aggregator:
    """Top-level verifier entry. Wires L0 → L1 → L2 → L3 escalation ladder.

    Per ARCHITECTURE.md Pattern 4 ("Cheap-deterministic-first ladder"):

    * L0 push events (drain AXObserverManager + NSWorkspace + kqueue futures).
    * L1 cheap diff (CGWindowList + NSPasteboard.changeCount + ROI dHash).
    * Both run IN PARALLEL via ``anyio.create_task_group``.
    * Confidence is computed via ``WeightedVote.aggregate(action_class, signals)``.
    * Escalation:
        - ``confidence >= 0.50`` → VERIFIED, no L2/L3 calls (the <50ms path).
        - ``0.30 <= confidence < 0.50`` → L2 runs, may boost above 0.50.
        - ``confidence < 0.30`` → L2 runs as deterministic try; if STILL
          below 0.30, L3 is invoked (raises in Phase 1, caught + logged).
    * Result is a ``HoarePost`` whose ``verified`` flag matches
      ``confidence >= VERIFIED_THRESHOLD`` (0.50).

    Public surface:
        agg = Aggregator(l0, l1, l2, l3, vote)
        # caller has already called manager.expect(...) BEFORE firing
        # caller has captured before_l1 = await l1.snapshot(target) BEFORE firing
        # caller has captured before_l2 = await l2.snapshot(target, ax) BEFORE firing
        # caller fires action via translator/channel
        post = await agg.verify(
            action, target, notifs, before_l1,
            before_l2=before_l2,
            ax_element=ax_element,
            expected_text="5",
        )
    """

    def __init__(
        self,
        l0: L0Push,
        l1: L1Cheap,
        l2: L2Medium,
        l3: L3Contract,
        vote: WeightedVote,
    ) -> None:
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3
        self._vote = vote
        self._log = structlog.get_logger()

    async def verify(
        self,
        action: ActionCanonical,
        target: UIElement,
        notifs: list[str],
        before_l1: L1Snapshot,
        ax_element: Any = None,
        before_l2: Optional[L2Snapshot] = None,
        expected_text: Optional[str] = None,
        timeout_ms: int = 50,
    ) -> HoarePost:
        """Run the L0 → L1 → L2 → L3 escalation ladder; return HoarePost.

        Caller MUST have:
        1. Subscribed AX notifications via ``axmgr.expect()`` BEFORE firing.
        2. Captured ``before_l1 = await l1.snapshot(target)`` BEFORE firing.
        3. (Optional) Captured ``before_l2`` BEFORE firing — required only
           if L2 escalation is desired (otherwise L2 is skipped).
        4. Fired the action via translator/channel.

        Args:
            action: The ActionCanonical that just fired. ``action.action_type``
                drives weight selection in WeightedVote (e.g. "click", "type",
                "scroll", "set_value").
            target: UIElement we operated on. ``target.composite_key`` flows
                into ``HoarePost.target_key``.
            notifs: AX notifications passed to L0Push.collect.
            before_l1: pre-action L1Snapshot captured by caller.
            ax_element: opaque AXUIElement ref handed through to L0Push and L2.
            before_l2: pre-action L2Snapshot. If None, L2 escalation is
                skipped (and L3 is too — there's no deterministic L2 to
                exhaust before LLM fallback).
            expected_text: optional text the caller expects to see post-action
                (e.g. "5" after clicking the 5 button on Calculator). L2
                emits ``l2.expected_text_present`` accordingly.
            timeout_ms: budget for L0 collect (default 50 ms).

        Returns:
            HoarePost with ``verified == (confidence >= 0.50)``,
            ``tier_signals = {"L0": <max ax.* signal>, "L1": <max l1.* signal>,
            "L2": <l2 boost or None>, "L3": <l3 conf or None>}``.
        """
        t_start = time.monotonic()
        l0_signals: dict[str, float] = {}
        l1_signals: dict[str, float] = {}

        # 1. L0 + L1 in parallel (Plan 05 baseline).
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

        merged: dict[str, float] = {**l0_signals, **l1_signals}
        confidence = self._vote.aggregate(action.action_type, merged)

        tier_signals: dict[str, Optional[float]] = {
            "L0": self._signal_max(l0_signals, prefix="ax."),
            "L1": self._signal_max(l1_signals, prefix="l1."),
            "L2": None,  # filled if L2 escalation runs
            "L3": None,  # filled if L3 escalation runs
        }

        # 2. L2 escalation: confidence below VERIFIED threshold AND we have
        # the pre-state + ax_element to actually run L2 against. The L2 step
        # is "deterministic try before LLM" — so we ALWAYS run it before L3.
        if (
            confidence < VERIFIED_THRESHOLD
            and before_l2 is not None
            and ax_element is not None
        ):
            self._log.info(
                "verifier.escalating_to_l2",
                confidence_before=confidence,
                action_id=action.id,
            )
            l2_signals = await self._l2.run(
                target=target,
                ax_element=ax_element,
                before=before_l2,
                expected_text=expected_text,
            )
            merged.update(l2_signals)

            # L2 boost = max of L2 signals; truncation halves the boost
            # (per VERIFY-06: truncated walker = lower trust).
            l2_boost = max(l2_signals.values()) if l2_signals else 0.0
            if l2_signals.get("l2.walker_truncated", 0.0) >= 1.0:
                l2_boost *= 0.5  # truncation penalty
            confidence = min(1.0, confidence + 0.2 * l2_boost)
            tier_signals["L2"] = l2_boost

        # 3. L3 escalation: still below the L3 threshold after L2.
        # Phase 1: L3Stub.verify raises NotImplementedError. We catch the
        # exception, emit a structured warning event, and return a
        # HoarePost(verified=False) so the caller can react.
        if confidence < L3_ESCALATE_THRESHOLD:
            self._log.warning(
                "verifier.escalating_to_l3",
                confidence_after_l2=confidence,
                action_id=action.id,
            )
            try:
                # Build a HoarePost projection to hand to the LLM (Phase 4).
                # Phase 1 stub ignores the args entirely.
                projected = HoarePost(
                    target_key=target.composite_key,
                    confidence=confidence,
                    tier_signals=dict(tier_signals),
                    verified=False,
                    healed_to=None,
                    timestamp_ns=time.monotonic_ns(),
                )
                l3_conf, reasoning = await self._l3.verify(
                    None, projected, dict(merged)
                )
                confidence = l3_conf
                tier_signals["L3"] = l3_conf
                self._log.info(
                    "verifier.l3_returned",
                    confidence=l3_conf,
                    reasoning=reasoning,
                )
            except NotImplementedError as e:
                # Phase 1 invariant: L3 stub raises. Don't fail the verify —
                # emit structured event, mark verified=False, return HoarePost
                # so caller can handle. Phase 4 swaps in a real impl and this
                # branch becomes unreachable.
                self._log.warning(
                    "l3.unavailable_phase1",
                    reason=str(e),
                    action_id=action.id,
                )

        verified = confidence >= VERIFIED_THRESHOLD
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
