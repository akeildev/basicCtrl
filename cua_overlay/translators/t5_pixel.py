"""T5 Pixel Translator — delegates coordinates to T4, hashes pre-fire ROI.

Per CONTEXT.md D-07: T5 uses CGWindowList for screen reads + ImageHash dHash
for ROI verification + delegates coordinate resolution to T4 (uitag).

Per RESEARCH.md §Pattern 8.

D-14 default channel binding: T5 → C3 (CGEvent.postToPid with cursor).
"""
from __future__ import annotations

from typing import Literal, Optional

import structlog

from cua_overlay.state.graph import Bbox
from cua_overlay.translators.base import TargetSpec, TranslatorTarget
from cua_overlay.translators.t4_vision import T4VisionTranslator


_log = structlog.get_logger()


class T5PixelTranslator:
    """T5 — last-resort pixel-only path. Delegates coords to T4; adds pre-fire
    phash for L1 ROI diff verification."""

    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T5"

    def __init__(self, t4: Optional[T4VisionTranslator] = None) -> None:
        self._t4 = t4 if t4 is not None else T4VisionTranslator()

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
    ) -> Optional[TranslatorTarget]:
        """Delegate coordinate resolution to T4; capture pre-fire ROI hash."""
        t4_target = await self._t4.resolve(bundle_id, pid, target_spec)
        if t4_target is None or t4_target.grounded_bbox is None:
            return None

        # Pre-action ROI hash for L1 verifier diff (Phase 1 L1Cheap consumes this).
        pre_phash = await self._capture_roi_phash(t4_target.grounded_bbox)

        # Reconstruct the TranslatorTarget with extras carrying pre_phash.
        extras = dict(t4_target.extras)
        if pre_phash:
            extras["pre_phash"] = pre_phash
        return TranslatorTarget(
            element=t4_target.element,
            ax_element=t4_target.ax_element,
            cdp_node_id=t4_target.cdp_node_id,
            cdp_session_id=t4_target.cdp_session_id,
            as_target_spec=t4_target.as_target_spec,
            grounded_bbox=t4_target.grounded_bbox,
            extras=extras,
        )

    async def _capture_roi_phash(self, bbox: Bbox) -> Optional[str]:
        """Capture screen ROI at bbox; return phash string. None on capture
        failure (allows fire to proceed without pre-hash)."""
        try:
            from PIL import Image  # type: ignore[import-not-found]
            import imagehash  # type: ignore[import-not-found]
            from CoreFoundation import (  # type: ignore[import-not-found]
                CFDataGetBytes,
                CFDataGetLength,
            )
            from Quartz import (  # type: ignore[import-not-found]
                CGDataProviderCopyData,
                CGImageGetDataProvider,
                CGImageGetHeight,
                CGImageGetWidth,
                CGRectMake,
                CGWindowListCreateImage,
                kCGNullWindowID,
                kCGWindowImageDefault,
                kCGWindowListOptionOnScreenOnly,
            )

            roi_rect = CGRectMake(bbox.x, bbox.y, bbox.w, bbox.h)
            cg_image = CGWindowListCreateImage(
                roi_rect,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageDefault,
            )
            if cg_image is None:
                return None
            w = int(CGImageGetWidth(cg_image))
            h = int(CGImageGetHeight(cg_image))
            data_provider = CGImageGetDataProvider(cg_image)
            cf_data = CGDataProviderCopyData(data_provider)
            ln = CFDataGetLength(cf_data)
            buf = bytearray(ln)
            CFDataGetBytes(cf_data, (0, ln), buf)
            img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
            return str(imagehash.phash(img))
        except Exception as exc:  # noqa: BLE001
            _log.debug("t5.phash_capture_failed", error=str(exc))
            return None

    async def validate(self, target: TranslatorTarget) -> bool:
        return target.grounded_bbox is not None
