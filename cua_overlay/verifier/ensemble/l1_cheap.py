"""L1 cheap-diff verifier — three sub-checks running in parallel.

Per VERIFY-05 + 01-RESEARCH.md "L1: Cheap diff (1-5ms target)":

* **L1a CGWindowList diff** (~1-2 ms) — added / removed / title-changed windows.
* **L1b NSPasteboard.changeCount** (<1 ms) — integer counter only.
  Threat T-1-03: pasteboard CONTENTS are NEVER read or logged. The signal is
  whether the integer changed; tests assert the signal value is an int/float
  and that no log event field carries a 'SECRET' string.
* **L1c pixel ROI dHash** (~10-20 ms with screenshot capture) — 64-bit
  fingerprint compared via Hamming distance; threshold 5 bits (~8% pixels).

The three sub-checks run inside ``anyio.create_task_group``. Sync helpers
are pushed to threads via ``asyncio.to_thread`` so the asyncio loop never
blocks on PyObjC C calls.

Total budget: <20 ms typical. Plan 01-09's Calculator demo is the live
benchmark anchor.
"""
from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass
from typing import Any, Optional

import anyio
import imagehash
import structlog
from PIL import Image

from cua_overlay.state.graph import Bbox, UIElement


# Hamming distance threshold for the dHash compare. 5 bits / 64 ≈ 8% change;
# matches the architecture-doc + research-doc default. ROI is 100×100 px so
# small text-cursor blinks don't cross 5 bits.
_DHASH_THRESHOLD_BITS: int = 5


@dataclass
class L1Snapshot:
    """Pre-action snapshot to diff against post-action state.

    All three sub-check sources are captured atomically so the diff is
    apples-to-apples.
    """

    window_list: dict[int, dict[str, Any]]
    pasteboard_change_count: int
    roi_dhash: Optional[str]  # hex string of 64-bit dHash, or None on capture fail
    captured_at: float


class L1Cheap:
    """L1 cheap-diff verifier: three sub-checks in parallel.

    Per VERIFY-05 + Pitfall research:

    * L1a CGWindowList diff (~1-2 ms): added / removed / title_changed windows.
    * L1b NSPasteboard.changeCount (<1 ms): integer counter
      (T-1-03: never logs contents — only the integer counters).
    * L1c pixel ROI dHash (~10-20 ms with screenshot capture): 64-bit
      fingerprint compare.

    Public surface:
        l1 = L1Cheap()
        before = await l1.snapshot(target)        # before action fires
        # ... fire action ...
        signals = await l1.run(target, before)    # diff against pre-state
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger()

    # ---------------------------------------------------------------- snapshot

    async def snapshot(self, target: UIElement) -> L1Snapshot:
        """Capture pre-action state. Total budget <20 ms.

        Three sync helpers run in parallel via ``anyio.create_task_group`` +
        ``asyncio.to_thread``.
        """
        t = time.monotonic()
        results: dict[str, Any] = {}

        async def _wl() -> None:
            results["window_list"] = await asyncio.to_thread(self._cgwindowlist_snapshot)

        async def _pb() -> None:
            results["pasteboard"] = await asyncio.to_thread(self._pasteboard_change_count)

        async def _roi() -> None:
            results["roi_dhash"] = await asyncio.to_thread(self._roi_dhash, target.bbox)

        async with anyio.create_task_group() as tg:
            tg.start_soon(_wl)
            tg.start_soon(_pb)
            tg.start_soon(_roi)

        return L1Snapshot(
            window_list=results["window_list"],
            pasteboard_change_count=results["pasteboard"],
            roi_dhash=results["roi_dhash"],
            captured_at=t,
        )

    # ---------------------------------------------------------------- run

    async def run(self, target: UIElement, before: L1Snapshot) -> dict[str, float]:
        """Capture post-action state in parallel; diff against ``before``.

        Returns a signal dict with keys:

        * ``l1.window_diff`` in [0..1] — count of added/removed/title-changed
          windows normalised by 3.
        * ``l1.pasteboard_changed`` in {0.0, 1.0} — integer counter delta.
        * ``l1.dhash_changed`` in {0.0, 1.0} — Hamming-threshold flip.
        """
        after = await self.snapshot(target)
        signals: dict[str, float] = {}

        # L1a: CGWindowList diff
        wl_diff = self._cgwindowlist_diff(before.window_list, after.window_list)
        changed_count = (
            len(wl_diff["added"]) + len(wl_diff["removed"]) + len(wl_diff["title_changed"])
        )
        signals["l1.window_diff"] = min(1.0, changed_count / 3.0)

        # L1b: pasteboard delta (T-1-03: integer-only; NEVER reads contents)
        if after.pasteboard_change_count != before.pasteboard_change_count:
            signals["l1.pasteboard_changed"] = 1.0
            # CRITICAL: log only the integer counters, NEVER any contents.
            # T-1-03 mitigation; test_no_pasteboard_contents_logged verifies.
            self._log.debug(
                "l1.pasteboard_changed",
                before_count=before.pasteboard_change_count,
                after_count=after.pasteboard_change_count,
            )
        else:
            signals["l1.pasteboard_changed"] = 0.0

        # L1c: dHash compare
        if before.roi_dhash and after.roi_dhash:
            try:
                bh = imagehash.hex_to_hash(before.roi_dhash)
                ah = imagehash.hex_to_hash(after.roi_dhash)
                distance = abs(bh - ah)
                signals["l1.dhash_changed"] = (
                    1.0 if distance > _DHASH_THRESHOLD_BITS else 0.0
                )
            except Exception as e:
                self._log.warning("l1.dhash_compare_failed", error=str(e))
                signals["l1.dhash_changed"] = 0.0
        else:
            # No fingerprint on either side; treat as no signal.
            signals["l1.dhash_changed"] = 0.0

        return signals

    # ---------------------------------------------------------------- helpers (sync, run in to_thread)

    def _cgwindowlist_snapshot(self) -> dict[int, dict[str, Any]]:
        """Snapshot all on-screen windows owned by foreground apps.

        Returns: ``{window_number: {"title": str, "owner_pid": int, "level": int}}``.
        Returns empty dict on PyObjC unavailability or capture failure.
        """
        try:
            from Quartz import (  # type: ignore[import-not-found]
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGWindowListExcludeDesktopElements,
                kCGNullWindowID,
            )
            info = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
                kCGNullWindowID,
            )
            return {
                int(w["kCGWindowNumber"]): {
                    "title": str(w.get("kCGWindowName", "")),
                    "owner_pid": int(w.get("kCGWindowOwnerPID", 0)),
                    "level": int(w.get("kCGWindowLayer", 0)),
                }
                for w in info or []
            }
        except Exception:
            return {}

    def _cgwindowlist_diff(
        self,
        before: dict[int, dict[str, Any]],
        after: dict[int, dict[str, Any]],
    ) -> dict[str, list[int]]:
        """Compute added / removed / title-changed window IDs."""
        return {
            "added": [k for k in after if k not in before],
            "removed": [k for k in before if k not in after],
            "title_changed": [
                k
                for k in after
                if k in before and after[k]["title"] != before[k]["title"]
            ],
        }

    def _pasteboard_change_count(self) -> int:
        """T-1-03: returns ONLY the integer counter — NEVER reads contents.

        ``NSPasteboard.changeCount()`` is a monotonically increasing integer
        that increments on any pasteboard activity. We never call
        ``stringForType:`` or ``dataForType:``; the contents are out of scope
        for Phase 1.
        """
        try:
            from AppKit import NSPasteboard  # type: ignore[import-not-found]
            return int(NSPasteboard.generalPasteboard().changeCount())
        except Exception:
            return 0

    def _roi_dhash(self, bbox: Bbox) -> Optional[str]:
        """Capture a 100×100 px ROI around ``bbox.centroid``, compute dHash, return hex.

        Returns None on capture failure (caller treats as 'no signal').

        Phase 1 uses the deprecated-but-still-working ``CGWindowListCreateImage``
        path because it's the simplest API that gives us a CGImage we can
        ``imagehash.dhash`` over. Phase 2 may switch to ScreenCaptureKit if the
        deprecation cost matters.
        """
        try:
            from Quartz import (  # type: ignore[import-not-found]
                CGRectMake,
                CGWindowListCreateImage,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageDefault,
            )
            cx, cy = bbox.centroid
            rect = CGRectMake(cx - 50, cy - 50, 100, 100)
            cg_image = CGWindowListCreateImage(
                rect,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageDefault,
            )
            if cg_image is None:
                return None
            pil_img = self._cgimage_to_pil(cg_image)
            if pil_img is None:
                return None
            h = imagehash.dhash(pil_img, hash_size=8)
            return str(h)
        except Exception:
            return None

    def _cgimage_to_pil(self, cg_image: Any) -> Optional[Image.Image]:
        """CGImage → PNG bytes → PIL.Image via NSBitmapImageRep round-trip.

        Phase 1 cheap path. The PNG encode is the slow step (~5-10 ms for
        100×100 px); PNG-to-PIL is sub-millisecond.
        """
        try:
            from AppKit import NSBitmapImageRep, NSPNGFileType  # type: ignore[import-not-found]
            rep = NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
            png_data = rep.representationUsingType_properties_(NSPNGFileType, None)
            return Image.open(io.BytesIO(bytes(png_data)))
        except Exception:
            return None
