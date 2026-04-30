"""L2 medium-cost verifier — Vision OCR ROI diff + depth-limited AX subtree.

Per VERIFY-06 + 01-RESEARCH.md "L2: Medium (50-200ms target)":

* **L2a Vision OCR text diff** (~50-100 ms) — capture a 100x100 px ROI
  around ``target.bbox.centroid`` and run ``ocrmac.OCR(...)`` (thin shim
  over Apple Vision's ``VNRecognizeTextRequest``). Compare pre/post ROI
  text strings for change detection and optional ``expected_text``
  presence.
* **L2b AX depth-limited subtree** (~10-50 ms with rate-limit) —
  ``walk_subtree(..., max_depth=3, max_children=50, max_nodes=500)`` —
  the ONLY sanctioned way to walk an AX hierarchy in cua-maximalist.
  Reuses Plan 03's walker verbatim; never re-implements raw AX recursion
  (Pitfall P3 hard rule: full recursive AX = 15-20 s on Safari).

Both sub-checks run inside ``anyio.create_task_group``. Latency budget
50-200 ms total. Walker rate-limited via Plan 03's ``TokenBucket``.

Phase 1 invariant: the Calculator demo (Plan 09) MUST NOT trigger L2 —
L0+L1 alone produce confidence >= 0.50. L2 escalation only fires when
``L3_ESCALATE_THRESHOLD <= confidence < VERIFIED_THRESHOLD`` (the
"corridor" between 0.30 and 0.50). Plan 06 Task 3 wires the escalation
in the Aggregator.

Per Pitfall P3 (full recursive AX) the walker delegation is enforced by
unit tests:

* ``test_walk_uses_max_depth_3_default`` — source-grep checks no
  ``max_depth >= 4`` override.
* ``test_no_full_recursion`` — source-grep checks the L2 module never
  reaches into raw AX read primitives. Delegation through the Plan 03
  walker is the only sanctioned path.

The Vision OCR latency on macOS 26 with ANE is reportedly 50-200 ms for
a 100x100 ROI; under test we mock the OCR helper so the unit suite stays
deterministic and fast.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

import anyio
import structlog

from cua_overlay.ax.rate_limit import TokenBucket
from cua_overlay.ax.walker import walk_subtree
from cua_overlay.state.graph import Bbox, UIElement


@dataclass
class L2Snapshot:
    """Pre-action L2 snapshot used for diffing post-action.

    Captured atomically via ``L2Medium.snapshot(target, ax_element)`` —
    OCR ROI text + walker node count + walker truncated flag — so the
    pre/post diff is apples-to-apples.
    """

    ocr_text: str
    walker_nodes: int
    walker_truncated: bool
    captured_at: float


class L2Medium:
    """L2 medium-cost verifier: Vision OCR + depth-limited walker.

    Per VERIFY-06: max 3 levels, 50 children, 500 nodes (the walker
    enforces these via ``walk_subtree``'s defaults). Per Pitfall P3:
    NEVER full recursive — always walks via ``walk_subtree``.

    Phase 1 scope: scaffolding wired and unit-tested. The Calculator
    demo (Plan 09) MUST NOT trigger L2 — L0+L1 alone produce
    confidence >= 0.50.

    Public surface:
        l2 = L2Medium(bucket)
        before = await l2.snapshot(target, ax_element)   # before action
        # ... fire action ...
        signals = await l2.run(target, ax_element, before, expected_text="5")
    """

    def __init__(self, bucket: Optional[TokenBucket] = None) -> None:
        self._bucket = bucket or TokenBucket()
        self._log = structlog.get_logger()

    # ---------------------------------------------------------------- snapshot

    async def snapshot(
        self, target: UIElement, ax_element: Any = None
    ) -> L2Snapshot:
        """Capture pre-action OCR + walker state IN PARALLEL via anyio.

        Both sub-checks run concurrently via ``anyio.create_task_group``
        so the latency budget is dominated by the slowest leg
        (~50-200 ms typically).

        ``ax_element=None`` → walker leg short-circuits to (0, False);
        OCR still runs. Tests construct snapshots with concrete walker
        results via patching ``walk_subtree``.
        """
        t = time.monotonic()
        results: dict[str, Any] = {
            "ocr_text": "",
            "walker_nodes": 0,
            "walker_truncated": False,
        }

        async def _ocr() -> None:
            results["ocr_text"] = await self._capture_ocr(target.bbox)

        async def _walk() -> None:
            if ax_element is None:
                # No AX element handed in — walker leg degrades gracefully.
                return
            wr = await walk_subtree(
                ax_element,
                pid=target.pid,
                bundle_id=target.bundle_id,
                bucket=self._bucket,
            )
            results["walker_nodes"] = len(wr.nodes)
            results["walker_truncated"] = wr.truncated

        async with anyio.create_task_group() as tg:
            tg.start_soon(_ocr)
            tg.start_soon(_walk)

        return L2Snapshot(
            ocr_text=results["ocr_text"],
            walker_nodes=int(results["walker_nodes"]),
            walker_truncated=bool(results["walker_truncated"]),
            captured_at=t,
        )

    # ---------------------------------------------------------------- run

    async def run(
        self,
        target: UIElement,
        ax_element: Any,
        before: L2Snapshot,
        expected_text: Optional[str] = None,
    ) -> dict[str, float]:
        """Capture post-action L2 snapshot and diff against ``before``.

        Returns a signal dict with keys:

        * ``l2.ocr_text_changed`` ∈ {0.0, 1.0} — pre/post OCR text differ.
        * ``l2.expected_text_present`` ∈ {0.0, 1.0} — present iff
          ``expected_text`` is supplied AND found in post OCR.
        * ``l2.subtree_size_changed`` ∈ [0.0, 1.0] — abs node-count delta
          normalised by pre-state size (clamped to 1.0).
        * ``l2.walker_truncated`` ∈ {0.0, 1.0} — truncation in either
          pre or post snapshot — confidence-reducer per VERIFY-06.

        All signal values are floats in [0.0, 1.0] so the WeightedVote
        aggregator can blend them with L0/L1 signals uniformly.
        """
        after = await self.snapshot(target, ax_element)
        signals: dict[str, float] = {}

        # L2a-i: OCR text change
        before_text = (before.ocr_text or "").strip()
        after_text = (after.ocr_text or "").strip()
        if before_text and after_text:
            signals["l2.ocr_text_changed"] = 0.0 if before_text == after_text else 1.0
        else:
            # Either side empty → no signal
            signals["l2.ocr_text_changed"] = 0.0

        # L2a-ii: expected text presence (only when caller specifies)
        if expected_text:
            signals["l2.expected_text_present"] = (
                1.0 if expected_text in after.ocr_text else 0.0
            )

        # L2b-i: subtree node count change (normalised to [0, 1])
        delta = abs(after.walker_nodes - before.walker_nodes)
        denom = max(1, before.walker_nodes)
        signals["l2.subtree_size_changed"] = float(min(1.0, delta / denom))

        # L2b-ii: walker truncated → confidence-reducer per VERIFY-06.
        # If EITHER snapshot truncated, raise the flag — verifier interprets
        # this as "L2 saw a partial view, lower trust accordingly".
        signals["l2.walker_truncated"] = (
            1.0 if (before.walker_truncated or after.walker_truncated) else 0.0
        )

        self._log.info(
            "l2.medium_run",
            target_key=target.composite_key,
            signals=signals,
            before_nodes=before.walker_nodes,
            after_nodes=after.walker_nodes,
        )
        return signals

    # ---------------------------------------------------------------- ocr capture

    async def _capture_ocr(self, bbox: Bbox) -> str:
        """Capture a 100x100 ROI around ``bbox.centroid`` and OCR via ocrmac.

        Reuses Plan 05's L1Cheap._cgimage_to_pil helper to convert the
        CGImage to a PIL.Image (NSBitmapImageRep round-trip). Then hands
        the PIL.Image to ``ocrmac.OCR(...).recognize()``.

        Wrapped in ``asyncio.to_thread`` so the asyncio loop never blocks
        on PyObjC C calls. Returns "" on any framework failure (caller
        treats empty OCR as "no signal").
        """
        def _sync() -> str:
            try:
                from ocrmac import ocrmac  # type: ignore[import-not-found]
                from Quartz import (  # type: ignore[import-not-found]
                    CGRectMake,
                    CGWindowListCreateImage,
                    kCGNullWindowID,
                    kCGWindowImageDefault,
                    kCGWindowListOptionOnScreenOnly,
                )

                from cua_overlay.verifier.ensemble.l1_cheap import L1Cheap

                cx, cy = bbox.centroid
                rect = CGRectMake(cx - 50, cy - 50, 100, 100)
                cg_image = CGWindowListCreateImage(
                    rect,
                    kCGWindowListOptionOnScreenOnly,
                    kCGNullWindowID,
                    kCGWindowImageDefault,
                )
                if cg_image is None:
                    return ""
                # Reuse the CGImage → PIL bridge from L1Cheap (instance helper).
                capture = L1Cheap()
                pil_img = capture._cgimage_to_pil(cg_image)
                if pil_img is None:
                    return ""
                annotations = ocrmac.OCR(pil_img).recognize()
                return " ".join(a[0] for a in annotations) if annotations else ""
            except Exception:
                return ""

        return await asyncio.to_thread(_sync)
