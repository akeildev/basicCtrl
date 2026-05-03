"""Unit tests for UI-TARS grounder with sanity gate + uitag fallback (P4, D-05).

Per PLAN 04-02:
- Test 1: UI-TARS normal bbox (not center) → sanity_gate passes
- Test 2: UI-TARS outputs (W/2, H/2) → sanity_gate fails, calls fallback_to_uitag()
- Test 3: Differential grounding IoU <0.5 → falls to OCR
- Test 4: P4 telemetry counter — screen-center rejections logged
"""
import pytest
from unittest import mock
from PIL import Image
import io

from basicctrl.cognition.grounder import Grounder


class TestGrounder:
    """Test UI-TARS grounder with P4 sanity gate + uitag fallback."""

    @pytest.fixture
    def grounder(self):
        """Fixture: Fresh grounder instance."""
        return Grounder()

    @pytest.fixture
    def sample_screenshot_bytes(self):
        """Fixture: Sample PNG screenshot bytes (1920x1080)."""
        img = Image.new("RGB", (1920, 1080), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @pytest.mark.asyncio
    async def test_sanity_gate_passes_on_normal_bbox(self, grounder):
        """Test 1: Normal bbox (not center) passes sanity gate."""
        bbox = (100.0, 100.0, 200.0, 50.0)  # Normal coords
        screenshot_w = 1920
        screenshot_h = 1080

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        assert passes is True

    @pytest.mark.asyncio
    async def test_sanity_gate_rejects_screen_center(self, grounder):
        """Test 2: Screen-center output rejected (P4 mitigation)."""
        screenshot_w = 1920
        screenshot_h = 1080
        center_x = screenshot_w / 2.0  # 960
        center_y = screenshot_h / 2.0  # 540

        # Bbox at screen center
        bbox = (center_x, center_y, 50.0, 50.0)

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        assert passes is False

    @pytest.mark.asyncio
    async def test_sanity_gate_rejects_within_threshold(self, grounder):
        """Test P4: Bbox within ±10px of center is rejected."""
        screenshot_w = 1920
        screenshot_h = 1080
        center_x = screenshot_w / 2.0
        center_y = screenshot_h / 2.0

        # Within ±10px threshold (5px offset)
        bbox = (center_x + 5, center_y + 5, 50.0, 50.0)

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        assert passes is False

    @pytest.mark.asyncio
    async def test_sanity_gate_passes_just_outside_threshold(self, grounder):
        """Test: Bbox just outside ±10px threshold passes."""
        screenshot_w = 1920
        screenshot_h = 1080
        center_x = screenshot_w / 2.0
        center_y = screenshot_h / 2.0

        # At 11px offset (outside threshold)
        bbox = (center_x + 11, center_y + 11, 50.0, 50.0)

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        assert passes is True

    @pytest.mark.asyncio
    async def test_differential_iou_above_threshold(self, grounder):
        """Test 3a: Differential grounding — IoU >0.5 passes."""
        # Overlapping boxes with IoU ~0.8
        ui_tars_bbox = (100.0, 100.0, 100.0, 100.0)
        uitag_bbox = (150.0, 150.0, 100.0, 100.0)

        # IoU = intersection / union
        # intersection: (100,100) to (150,150) = 50×50 = 2500
        # union: 10000 + 10000 - 2500 = 17500
        # IoU = 2500/17500 ≈ 0.143 (low but let's test agreement)

        # Better test: nearly identical boxes
        ui_tars_bbox = (100.0, 100.0, 100.0, 100.0)
        uitag_bbox = (100.0, 100.0, 100.0, 100.0)

        passes = await grounder.differential_grounding(ui_tars_bbox, uitag_bbox)
        assert passes is True

    @pytest.mark.asyncio
    async def test_differential_iou_below_threshold(self, grounder):
        """Test 3b: Differential grounding — IoU <0.5 fails (disagreement)."""
        # Non-overlapping boxes
        ui_tars_bbox = (100.0, 100.0, 100.0, 100.0)
        uitag_bbox = (300.0, 300.0, 100.0, 100.0)

        # No intersection → IoU = 0
        passes = await grounder.differential_grounding(ui_tars_bbox, uitag_bbox)
        assert passes is False

    def test_iou_computation_identical_boxes(self, grounder):
        """Test IoU computation: identical boxes → IoU = 1.0."""
        bbox = (100.0, 100.0, 200.0, 150.0)

        iou = grounder._compute_iou(bbox, bbox)
        assert iou == 1.0

    def test_iou_computation_non_overlapping(self, grounder):
        """Test IoU computation: non-overlapping boxes → IoU = 0."""
        bbox1 = (0.0, 0.0, 100.0, 100.0)
        bbox2 = (200.0, 200.0, 100.0, 100.0)

        iou = grounder._compute_iou(bbox1, bbox2)
        assert iou == 0.0

    def test_iou_computation_partial_overlap(self, grounder):
        """Test IoU computation: partial overlap."""
        bbox1 = (0.0, 0.0, 100.0, 100.0)
        bbox2 = (50.0, 50.0, 100.0, 100.0)

        # Intersection: (50,50) to (100,100) = 50×50 = 2500
        # Union: 10000 + 10000 - 2500 = 17500
        # IoU = 2500/17500 ≈ 0.143
        iou = grounder._compute_iou(bbox1, bbox2)
        assert 0.14 < iou < 0.15

    @pytest.mark.asyncio
    async def test_sanity_gate_rejects_variant_one_axis(self, grounder):
        """Test: Only x within threshold, but y outside → passes."""
        screenshot_w = 1920
        screenshot_h = 1080
        center_x = screenshot_w / 2.0
        center_y = screenshot_h / 2.0

        # x near center, y far away
        bbox = (center_x + 5, center_y + 100, 50.0, 50.0)

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        # Both x AND y must be within threshold to reject
        assert passes is True

    @pytest.mark.asyncio
    async def test_sanity_gate_negative_coordinates(self, grounder):
        """Test: Negative coordinates (off-screen) pass gate."""
        bbox = (-100.0, -100.0, 50.0, 50.0)
        screenshot_w = 1920
        screenshot_h = 1080

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        assert passes is True

    @pytest.mark.asyncio
    async def test_sanity_gate_large_screen_dimensions(self, grounder):
        """Test: Sanity gate scales with large screen dimensions."""
        screenshot_w = 5120  # Ultra-wide
        screenshot_h = 2880
        center_x = screenshot_w / 2.0
        center_y = screenshot_h / 2.0

        # Center rejection threshold is absolute ±10px
        bbox = (center_x, center_y, 100.0, 100.0)

        passes = await grounder.sanity_gate(bbox, screenshot_w, screenshot_h)
        assert passes is False

    @pytest.mark.asyncio
    async def test_mlx_vlm_unavailable_returns_zero_bbox(self, grounder, sample_screenshot_bytes):
        """Test: mlx-vlm unavailable returns zero bbox gracefully."""
        with mock.patch("basicctrl.cognition.grounder.HAS_MLX_VLM", False):
            bbox, conf = await grounder.ground_ui_tars(sample_screenshot_bytes, "test")

        assert bbox == (0, 0, 0, 0)
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_uitag_unavailable_returns_zero_bbox(self, grounder, sample_screenshot_bytes):
        """Test: uitag unavailable returns zero bbox gracefully."""
        with mock.patch("basicctrl.cognition.grounder.HAS_UITAG", False):
            bbox, conf = await grounder.fallback_to_uitag(sample_screenshot_bytes, "test")

        assert bbox == (0, 0, 0, 0)
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_ground_ui_tars_with_sanity_gate_integration(self, grounder, sample_screenshot_bytes):
        """Integration: ground_ui_tars applies sanity gate."""
        # Mock mlx-vlm availability
        with mock.patch("basicctrl.cognition.grounder.HAS_MLX_VLM", True):
            # Mock mlx-vlm to return center coords
            with mock.patch.object(
                grounder,
                "_run_ui_tars_inference",
                return_value=((960, 540, 50, 50), 0.9),  # Center
            ):
                # Mock fallback to return valid coords
                with mock.patch.object(
                    grounder,
                    "fallback_to_uitag",
                    return_value=((100, 100, 50, 50), 0.8),
                ):
                    bbox, conf = await grounder.ground_ui_tars(sample_screenshot_bytes, "test")

        # Should have fallen back due to sanity gate rejection
        assert bbox == (100, 100, 50, 50)
        assert conf == 0.8

    def test_center_rejection_threshold_constant(self, grounder):
        """Test: CENTER_REJECTION_THRESHOLD is set correctly (P4)."""
        assert grounder.CENTER_REJECTION_THRESHOLD == 10

    def test_differential_iou_threshold_constant(self, grounder):
        """Test: MIN_DIFFERENTIAL_IOU is set correctly (D-06)."""
        assert grounder.MIN_DIFFERENTIAL_IOU == 0.5
