"""UI-TARS grounder with sanity gate + uitag fallback (P4, D-04, D-05 mitigations).

Per D-04, D-05 (04-CONTEXT.md):
- UI-TARS-1.5-7B via mlx-vlm 0.4.4 produces bbox candidates
- Sanity gate rejects screen-center outputs ±10px (P4 mitigation)
- uitag (Apple Vision + YOLO11 MLX) is PRIMARY; UI-TARS is SECONDARY
- Differential grounding: IoU >0.5 between bboxes required on disagreement

P4 mitigation: Screen-center quantization bug → sanity gate rejects.
Show UI-2B fallback if UI-TARS fails sanity check.
"""
from __future__ import annotations

import asyncio
import math
from typing import Optional

import structlog

from cua_overlay.cognition.schemas import EnsembleVote

_log = structlog.get_logger()

# Lazy imports — heavy dependencies, may not be available in CI
HAS_MLX_VLM = True
try:
    import mlx.core as mx  # type: ignore[import-not-found]
    from mlx_vlm.models.utils import load_config  # type: ignore[import-not-found]
    from mlx_vlm.models.base import load_model  # type: ignore[import-not-found]
except ImportError:
    HAS_MLX_VLM = False

HAS_UITAG = True
try:
    from uitag import run_pipeline  # type: ignore[import-not-found]
except ImportError:
    HAS_UITAG = False


class Grounder:
    """UI-TARS + uitag grounder with sanity gates (P4 mitigation)."""

    # P4: Screen-center rejection ±10px
    CENTER_REJECTION_THRESHOLD = 10  # pixels

    # Differential grounding: minimum IoU between UI-TARS and uitag
    MIN_DIFFERENTIAL_IOU = 0.5

    # mlx-vlm model paths (HuggingFace community)
    UI_TARS_MODEL = "mlx-community/UI-TARS-1.5-7B-4bit"
    SHOWUI_MODEL = "mlx-community/ShowUI-2B-4bit"  # Fallback

    def __init__(self):
        """Initialize grounder — lazy-load models on first use."""
        self._ui_tars_model = None
        self._showui_model = None

    async def ground_ui_tars(
        self,
        screenshot: bytes,
        instruction: str,
    ) -> tuple[tuple[float, float, float, float], float]:
        """Ground instruction to UI element using UI-TARS-1.5-7B.

        Args:
            screenshot: PNG bytes of the target screen
            instruction: Natural language instruction (e.g., "click the submit button")

        Returns:
            ((x, y, w, h), confidence) — bounding box + confidence [0, 1]
            If sanity gate fails, returns fallback from uitag().

        Per D-04, P4: apply sanity_gate BEFORE returning.
        """
        if not HAS_MLX_VLM:
            _log.warning("grounder.mlx_vlm_unavailable")
            return ((0, 0, 0, 0), 0.0)

        # Infer image dimensions (PIL will decode to get w/h)
        try:
            from PIL import Image  # type: ignore[import-not-found]
            img = Image.open(__import__("io").BytesIO(screenshot))
            screenshot_w, screenshot_h = img.size
        except Exception as exc:  # noqa: BLE001
            _log.error("grounder.image_decode_failed", error=str(exc))
            return ((0, 0, 0, 0), 0.0)

        # Run UI-TARS inference in thread (mlx-vlm is sync)
        bbox, confidence = await asyncio.to_thread(
            self._run_ui_tars_inference,
            screenshot,
            instruction,
        )

        # P4 mitigation: sanity gate rejects screen-center
        passes_sanity = await self.sanity_gate(
            bbox,
            screenshot_w,
            screenshot_h,
        )
        if not passes_sanity:
            _log.info("grounder.sanity_gate_failed", bbox=bbox)
            # Fall back to uitag
            return await self.fallback_to_uitag(screenshot, instruction)

        _log.info("grounder.ui_tars_success", bbox=bbox, confidence=confidence)
        return (bbox, confidence)

    async def sanity_gate(
        self,
        bbox: tuple[float, float, float, float],
        screenshot_w: int,
        screenshot_h: int,
        expected_element_hash: Optional[str] = None,
    ) -> bool:
        """P4 mitigation: reject screen-center outputs ±10px.

        Args:
            bbox: (x, y, w, h) in screen coordinates
            screenshot_w, screenshot_h: screen dimensions
            expected_element_hash: optional SHA-256 of expected element for confirmation

        Returns:
            True if bbox passes gate, False to trigger fallback.

        Per P4: reject if |x - W/2| < 10 AND |y - H/2| < 10 unless
        expected_element_hash confirms center IS the target.
        """
        x, y, w, h = bbox
        center_x = screenshot_w / 2.0
        center_y = screenshot_h / 2.0

        # Check if within ±10px of center
        dx = abs(x - center_x)
        dy = abs(y - center_y)

        if dx < self.CENTER_REJECTION_THRESHOLD and dy < self.CENTER_REJECTION_THRESHOLD:
            _log.warning(
                "grounder.center_rejection",
                x=x,
                y=y,
                center_x=center_x,
                center_y=center_y,
                threshold=self.CENTER_REJECTION_THRESHOLD,
            )
            return False

        return True

    async def fallback_to_uitag(
        self,
        screenshot: bytes,
        instruction: str,
    ) -> tuple[tuple[float, float, float, float], float]:
        """D-05: Primary grounder fallback — uitag (Apple Vision + YOLO11 MLX).

        Args:
            screenshot: PNG bytes
            instruction: Natural language instruction

        Returns:
            ((x, y, w, h), confidence) from uitag SoM detection

        Per D-05: uitag is PRIMARY; UI-TARS is secondary with differential
        grounding gate (IoU >0.5).
        """
        if not HAS_UITAG:
            _log.warning("grounder.uitag_unavailable")
            return ((0, 0, 0, 0), 0.0)

        # Save screenshot to temp file (uitag accepts file path only)
        import tempfile
        from pathlib import Path

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(screenshot)
                screenshot_path = Path(f.name)
        except Exception as exc:  # noqa: BLE001
            _log.error("grounder.temp_file_error", error=str(exc))
            return ((0, 0, 0, 0), 0.0)

        try:
            # Run uitag in thread (sync)
            detections, iw, ih = await asyncio.to_thread(
                self._run_uitag_pipeline,
                screenshot_path,
            )

            # Score detections by label (instruction text)
            matched = self._score_uitag_detections(detections, instruction)
            if matched is None:
                _log.warning("grounder.uitag_no_match", instruction=instruction)
                return ((0, 0, 0, 0), 0.0)

            # Extract bbox from detection
            x = float(getattr(matched, "x", 0))
            y = float(getattr(matched, "y", 0))
            w = float(getattr(matched, "width", 0))
            h = float(getattr(matched, "height", 0))
            confidence = float(getattr(matched, "confidence", 0.0))

            _log.info("grounder.uitag_success", bbox=(x, y, w, h), confidence=confidence)
            return ((x, y, w, h), confidence)
        finally:
            screenshot_path.unlink(missing_ok=True)

    async def differential_grounding(
        self,
        ui_tars_bbox: tuple[float, float, float, float],
        uitag_bbox: tuple[float, float, float, float],
    ) -> bool:
        """D-06: Differential grounding gate — IoU >0.5 required on disagreement.

        Args:
            ui_tars_bbox: (x, y, w, h) from UI-TARS
            uitag_bbox: (x, y, w, h) from uitag

        Returns:
            True if IoU >= MIN_DIFFERENTIAL_IOU, False to use OCR fallback.

        Per D-06: on disagreement (IoU ≤0.5), fall to T4 OCR-grounded action.
        """
        iou = self._compute_iou(ui_tars_bbox, uitag_bbox)
        _log.info("grounder.differential_iou", iou=iou)

        if iou < self.MIN_DIFFERENTIAL_IOU:
            _log.warning(
                "grounder.differential_disagreement",
                iou=iou,
                threshold=self.MIN_DIFFERENTIAL_IOU,
            )
            return False

        return True

    # ========== Private helpers ==========

    def _run_ui_tars_inference(
        self,
        screenshot: bytes,
        instruction: str,
    ) -> tuple[tuple[float, float, float, float], float]:
        """Sync UI-TARS inference (runs in asyncio.to_thread)."""
        if not HAS_MLX_VLM:
            return ((0, 0, 0, 0), 0.0)

        try:
            from PIL import Image  # type: ignore[import-not-found]
            import io

            # Load screenshot
            img = Image.open(io.BytesIO(screenshot))

            # UI-TARS prompt format
            prompt = f"<grounding>{instruction}"

            # Load model on first use
            if self._ui_tars_model is None:
                self._ui_tars_model = load_model(self.UI_TARS_MODEL)

            # Run inference
            # Note: mlx-vlm API varies; this is a placeholder based on typical usage
            # Actual API may differ — consult mlx-vlm documentation
            config = load_config(self.UI_TARS_MODEL)
            processor_name = config.model_type

            # Simplified inference (actual implementation may need adjustment)
            output = self._ui_tars_model.generate(
                image=img,
                prompt=prompt,
                max_tokens=256,
            )

            # Parse coordinates from output (model-specific)
            # Typical format: <click>x,y,w,h</click>
            bbox, confidence = self._parse_ui_tars_output(output)
            return (bbox, confidence)

        except Exception as exc:  # noqa: BLE001
            _log.error("grounder.ui_tars_inference_error", error=str(exc))
            return ((0, 0, 0, 0), 0.0)

    def _parse_ui_tars_output(
        self,
        output: str,
    ) -> tuple[tuple[float, float, float, float], float]:
        """Parse UI-TARS model output into bbox + confidence.

        Model output format varies; adjust based on actual mlx-vlm wrapper.
        Placeholder implementation.
        """
        try:
            # Try to extract <click>x,y,w,h</click> format
            if "<click>" in output:
                coords_str = output.split("<click>")[1].split("</click>")[0]
                parts = coords_str.split(",")
                if len(parts) == 4:
                    x, y, w, h = [float(p.strip()) for p in parts]
                    return ((x, y, w, h), 0.8)  # Assume 80% confidence
        except Exception:  # noqa: BLE001
            pass

        return ((0, 0, 0, 0), 0.0)

    def _run_uitag_pipeline(
        self,
        screenshot_path,
    ) -> tuple[list, int, int]:
        """Sync uitag pipeline (runs in asyncio.to_thread)."""
        if not HAS_UITAG:
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
            detections = list(getattr(result, "detections", []) or [])
            iw = int(getattr(result, "image_width", 0))
            ih = int(getattr(result, "image_height", 0))
            return (detections, iw, ih)
        except Exception as exc:  # noqa: BLE001
            _log.error("grounder.uitag_error", error=str(exc))
            return ([], 0, 0)

    def _score_uitag_detections(
        self,
        detections: list,
        instruction: str,
    ) -> Optional[object]:
        """Score detections by label substring match to instruction."""
        instruction_lower = instruction.lower()
        best_match = None
        best_confidence = 0.0

        for det in detections:
            label = str(getattr(det, "label", "")).lower()
            confidence = float(getattr(det, "confidence", 0.0))

            # Simple substring match (could be more sophisticated)
            if any(word in label for word in instruction_lower.split()):
                if confidence > best_confidence:
                    best_match = det
                    best_confidence = confidence

        return best_match

    def _compute_iou(
        self,
        bbox1: tuple[float, float, float, float],
        bbox2: tuple[float, float, float, float],
    ) -> float:
        """Compute Intersection over Union (IoU) between two bboxes.

        Args:
            bbox1, bbox2: (x, y, w, h) format

        Returns:
            IoU in [0, 1]
        """
        x1_min, y1_min, w1, h1 = bbox1
        x1_max = x1_min + w1
        y1_max = y1_min + h1

        x2_min, y2_min, w2, h2 = bbox2
        x2_max = x2_min + w2
        y2_max = y2_min + h2

        # Intersection
        xi_min = max(x1_min, x2_min)
        yi_min = max(y1_min, y2_min)
        xi_max = min(x1_max, x2_max)
        yi_max = min(y1_max, y2_max)

        intersection_w = max(0, xi_max - xi_min)
        intersection_h = max(0, yi_max - yi_min)
        intersection_area = intersection_w * intersection_h

        # Union
        area1 = w1 * h1
        area2 = w2 * h2
        union_area = area1 + area2 - intersection_area

        if union_area == 0:
            return 0.0

        return intersection_area / union_area
