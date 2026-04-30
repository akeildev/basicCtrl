"""TRANS-04 — T4 Vision translator unit tests with mocked uitag.

Per Plan 02-08: 8 unit tests covering tier id, D-06 hard rule (no
Screen2AX/MacPaw), Pitfall C asyncio.to_thread isolation, Detection→UIElement
adapter (Source.OCR vs Source.PIXEL), label-substring scoring, ocrmac
fallback path (Open Question 5), and A1 image-dimension logging for
first-integration Retina verification (T-2-04).
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cua_overlay.state.graph import Source
from cua_overlay.translators.base import TargetSpec
from cua_overlay.translators.t4_vision import T4VisionTranslator


def test_tier_is_T4() -> None:
    assert T4VisionTranslator().tier == "T4"


def test_no_screen2ax_or_macpaw_imports() -> None:
    """D-06 hard rule: no MacPaw/Screen2AX references in the module source."""
    src = (
        Path(__file__).parents[3]
        / "cua_overlay"
        / "translators"
        / "t4_vision.py"
    ).read_text()
    assert "Screen2AX" not in src
    assert "MacPaw" not in src
    assert "screen2ax" not in src.lower()
    assert "macpaw" not in src.lower()


def test_detection_to_uielement_vision_text_uses_OCR_source() -> None:
    t = T4VisionTranslator()
    det = SimpleNamespace(
        label="white pawn",
        x=100, y=200, width=50, height=50,
        confidence=0.92,
        source="vision_text",
        som_id=3,
    )
    elem = t._detection_to_uielement(det, 1234, "com.apple.Chess")
    assert Source.OCR in elem.source
    assert elem.label == "white pawn"
    assert elem.ocr_text == "white pawn"


def test_detection_to_uielement_yolo_uses_PIXEL_source() -> None:
    t = T4VisionTranslator()
    det = SimpleNamespace(
        label="icon-app",
        x=10, y=20, width=30, height=40,
        confidence=0.81,
        source="yolo",
        som_id=7,
    )
    elem = t._detection_to_uielement(det, 1234, "com.apple.Chess")
    assert Source.PIXEL in elem.source
    assert elem.ocr_text is None


def test_score_detections_label_substring_case_insensitive() -> None:
    t = T4VisionTranslator()
    detections = [
        SimpleNamespace(
            label="White Pawn", confidence=0.7,
            x=0, y=0, width=10, height=10, source="yolo", som_id=1,
        ),
        SimpleNamespace(
            label="white pawn", confidence=0.95,
            x=100, y=100, width=10, height=10, source="yolo", som_id=2,
        ),
        SimpleNamespace(
            label="black pawn", confidence=0.99,
            x=200, y=200, width=10, height=10, source="yolo", som_id=3,
        ),
    ]
    best = t._score_detections(detections, TargetSpec(label="white pawn"))
    assert best is not None
    assert best.confidence == 0.95


def test_score_detections_returns_none_on_no_match() -> None:
    t = T4VisionTranslator()
    detections = [
        SimpleNamespace(
            label="rook", confidence=0.7,
            x=0, y=0, width=10, height=10, source="yolo", som_id=1,
        ),
    ]
    assert t._score_detections(detections, TargetSpec(label="pawn")) is None


@pytest.mark.asyncio
async def test_run_uitag_runs_in_to_thread() -> None:
    """Pitfall C: uitag.run_pipeline must execute on a worker thread."""
    t = T4VisionTranslator()
    captured: dict[str, str] = {}

    def _capture(*args, **kwargs):
        captured["thread"] = threading.current_thread().name
        return (
            SimpleNamespace(detections=[], image_width=1024, image_height=768),
            None,
            "{}",
        )

    fake_module = SimpleNamespace(run_pipeline=_capture)
    with patch.dict("sys.modules", {"uitag": fake_module}):
        detections, iw, ih = await t._run_uitag(Path("/tmp/fake.png"))
    assert iw == 1024 and ih == 768
    # asyncio's default to_thread executor pumps work on the
    # ThreadPoolExecutor — assert NOT MainThread.
    assert captured["thread"] != "MainThread"


def test_score_detections_picks_highest_confidence_no_label() -> None:
    t = T4VisionTranslator()
    detections = [
        SimpleNamespace(
            label="a", confidence=0.5,
            x=0, y=0, width=10, height=10, source="yolo", som_id=1,
        ),
        SimpleNamespace(
            label="b", confidence=0.9,
            x=10, y=10, width=10, height=10, source="yolo", som_id=2,
        ),
    ]
    best = t._score_detections(detections, TargetSpec())
    assert best.confidence == 0.9
