"""T4 Vision Translator — uitag 0.6.0 (Apple Vision + YOLO11 MLX) + ocrmac fallback.

Per CONTEXT.md D-05: uitag direct dep + ocrmac fallback. Per CONTEXT.md D-06:
the synthetic-AX-tree research alternative is OUT OF SCOPE in Phase 2 —
research repo, conflicts with pyobjc 12.1, not on PyPI. Per CONTEXT.md D-08:
transformers>=5.0.0 (uitag transitive).

Per RESEARCH.md §"Pattern 7" + Pitfall C — uitag is sync (Apple Vision +
YOLO11 inference, 1-5s); calling it directly in an async context freezes the
race orchestrator's event loop, defeating racing. ALWAYS wrap run_pipeline in
``await asyncio.to_thread(...)``.

Per RESEARCH.md A1 (Retina coordinate handling) — uitag does NOT document
Retina/scale handling. T4 logs (image_width, image_height) at every resolve
so the first-integration Chess test (Plan 02-12) surfaces whether
Detection.x/y/width/height are physical pixels (2× logical) or logical
points. T-2-04 mitigation: if a 2:1 mismatch is observed, apply a divisor
in _detection_to_uielement (work item for Plan 02-12 if needed).

D-14 default channel binding: T4 → C1 (public CGEvent). Channel C1 ships
in Plan 02-09; T4 itself has no fire-path here.
"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import structlog

from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TargetSpec, TranslatorTarget


_log = structlog.get_logger()


class T4VisionTranslator:
    """T4 — uitag SoM + Apple Vision OCR (ocrmac) for non-AX apps."""

    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T4"

    async def _screenshot_to_path(self, pid: int) -> Optional[Path]:
        """Capture target window screenshot to a temp PNG file. uitag accepts
        file path only (NOT PIL.Image)."""
        try:
            # Reuse Phase 1's L1 capture path — CGWindowListCreateImage.
            from Quartz import (  # type: ignore[import-not-found]
                CGRectInfinite,
                CGWindowListCreateImage,
                kCGNullWindowID,
                kCGWindowImageDefault,
                kCGWindowListOptionOnScreenOnly,
            )
            cg_image = CGWindowListCreateImage(
                CGRectInfinite,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
                kCGWindowImageDefault,
            )
            if cg_image is None:
                return None
        except ImportError:
            _log.error("t4.quartz_unavailable")
            return None

        try:
            from PIL import Image  # type: ignore[import-not-found]

            # CGImage → PIL.Image via byte-buffer.
            from CoreFoundation import (  # type: ignore[import-not-found]
                CFDataGetBytes,
                CFDataGetLength,
            )
            from Quartz import (  # type: ignore[import-not-found]
                CGDataProviderCopyData,
                CGImageGetDataProvider,
                CGImageGetHeight,
                CGImageGetWidth,
            )

            w = int(CGImageGetWidth(cg_image))
            h = int(CGImageGetHeight(cg_image))
            data_provider = CGImageGetDataProvider(cg_image)
            cf_data = CGDataProviderCopyData(data_provider)
            ln = CFDataGetLength(cf_data)
            buf = bytearray(ln)
            CFDataGetBytes(cf_data, (0, ln), buf)
            img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
        except Exception as exc:  # noqa: BLE001
            _log.warning("t4.image_convert_failed", error=str(exc))
            return None

        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        path = Path(f.name)
        f.close()
        img.save(path)
        return path

    async def _run_uitag(
        self, screenshot_path: Path
    ) -> tuple[list, int, int]:
        """Run uitag.run_pipeline in a thread (Pitfall C — sync API)."""

        def _sync() -> tuple[list, int, int]:
            try:
                from uitag import run_pipeline  # type: ignore[import-not-found]
            except ImportError:
                _log.error("t4.uitag_unavailable")
                return ([], 0, 0)
            try:
                result, _annotated, _manifest = run_pipeline(
                    str(screenshot_path),
                    florence_task="<OD>",
                    overlap_px=50,
                    iou_threshold=0.5,
                    recognition_level="accurate",
                    use_yolo=True,
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("t4.uitag_pipeline_error", error=str(exc))
                return ([], 0, 0)
            detections = list(getattr(result, "detections", []) or [])
            iw = int(getattr(result, "image_width", 0))
            ih = int(getattr(result, "image_height", 0))
            return (detections, iw, ih)

        return await asyncio.to_thread(_sync)

    async def _ocrmac_fallback(
        self, screenshot_path: Path, target_spec: TargetSpec
    ) -> list:
        """ocrmac OCR fallback — returns ``list[(text, confidence, bbox)]``
        whose text matches target_spec.label substring case-insensitive.

        Triggered when uitag returns no detections for the requested label
        (Open Question 5 — non-UI canvases like Chess.app's 3D Metal board).
        """

        def _sync() -> list:
            try:
                import ocrmac  # type: ignore[import-not-found]
            except ImportError:
                return []
            try:
                results = ocrmac.OCR(str(screenshot_path)).recognize()
            except Exception:  # noqa: BLE001
                return []
            label_lower = (target_spec.label or "").lower()
            if not label_lower:
                return []
            return [r for r in results if label_lower in str(r[0]).lower()]

        return await asyncio.to_thread(_sync)

    def _detection_to_uielement(
        self, det: Any, pid: int, bundle_id: str
    ) -> UIElement:
        """Adapt uitag.Detection → UIElement.

        Detection fields: label, x, y, width, height, confidence, source, som_id.
        Per A1: assume logical points (verify via Plan 02-12 Chess integration test).
        """
        now = datetime.now(timezone.utc)
        label = getattr(det, "label", "") or ""
        x = float(getattr(det, "x", 0))
        y = float(getattr(det, "y", 0))
        w = float(getattr(det, "width", 0))
        h = float(getattr(det, "height", 0))
        confidence = float(getattr(det, "confidence", 0.0))
        det_source = str(getattr(det, "source", ""))
        som_id = int(getattr(det, "som_id", 0))
        ui_source = (
            Source.OCR if det_source == "vision_text" else Source.PIXEL
        )
        return UIElement(
            role="AXUnknown",
            role_path=f"AXVision/{det_source}[{som_id}]",
            label=label,
            bbox=Bbox(x=x, y=y, w=w, h=h),
            confidence=confidence,
            source=[ui_source],
            ocr_text=label if det_source == "vision_text" else None,
            discovered_at=now,
            last_seen_at=now,
            pid=pid,
            bundle_id=bundle_id,
            window_id=0,
        )

    def _score_detections(
        self, detections: list, target_spec: TargetSpec
    ) -> Optional[Any]:
        """Score by label substring (case-insensitive); pick highest confidence
        on tie. Returns None if no detections OR no label match."""
        label_lower = (target_spec.label or "").lower()
        if not label_lower:
            # No label specified — pick the highest-confidence detection
            # overall (best-effort behaviour for "click here" style requests).
            if not detections:
                return None
            return max(
                detections,
                key=lambda d: float(getattr(d, "confidence", 0.0)),
            )
        candidates = [
            d
            for d in detections
            if label_lower in str(getattr(d, "label", "")).lower()
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda d: float(getattr(d, "confidence", 0.0)),
        )

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
    ) -> Optional[TranslatorTarget]:
        """Capture screenshot, run uitag, score detections, fall back to ocrmac."""
        screenshot_path = await self._screenshot_to_path(pid)
        if screenshot_path is None:
            return None

        try:
            detections, image_width, image_height = await self._run_uitag(
                screenshot_path
            )
            # T-2-04 / A1 logging: every resolve emits image dimensions for
            # first-integration Retina verification (Plan 02-12 surfaces this).
            _log.info(
                "t4.uitag_completed",
                bundle_id=bundle_id,
                detection_count=len(detections),
                image_width=image_width,
                image_height=image_height,
            )

            best = self._score_detections(detections, target_spec)
            if best is None:
                # Fallback: ocrmac (Open Question 5 path).
                ocr_matches = await self._ocrmac_fallback(
                    screenshot_path, target_spec
                )
                if not ocr_matches:
                    _log.info(
                        "t4.no_match",
                        bundle_id=bundle_id,
                        label=target_spec.label,
                    )
                    return None
                # Use first ocrmac match.
                text, conf, bbox = ocr_matches[0]
                # ocrmac bbox is normalised [0..1]; multiply by image dims.
                if image_width and image_height:
                    bx = bbox[0] * image_width
                    by = bbox[1] * image_height
                    bw = bbox[2] * image_width
                    bh = bbox[3] * image_height
                else:
                    bx, by, bw, bh = bbox[0], bbox[1], bbox[2], bbox[3]
                now = datetime.now(timezone.utc)
                return TranslatorTarget(
                    element=UIElement(
                        role="AXUnknown",
                        role_path="AXVision/ocrmac[0]",
                        label=str(text),
                        bbox=Bbox(x=bx, y=by, w=bw, h=bh),
                        confidence=float(conf),
                        source=[Source.OCR],
                        ocr_text=str(text),
                        discovered_at=now,
                        last_seen_at=now,
                        pid=pid,
                        bundle_id=bundle_id,
                        window_id=0,
                    ),
                    grounded_bbox=Bbox(x=bx, y=by, w=bw, h=bh),
                )

            elem = self._detection_to_uielement(best, pid, bundle_id)
            return TranslatorTarget(
                element=elem,
                grounded_bbox=elem.bbox,
            )
        finally:
            screenshot_path.unlink(missing_ok=True)

    async def validate(self, target: TranslatorTarget) -> bool:
        """T4 validity = grounded_bbox present (vision-grounded coords are the
        only source of truth at fire time)."""
        return target.grounded_bbox is not None
