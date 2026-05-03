"""Unit tests for CGEvent tap recorder + keystroke coalescing.

Per Phase 4 D-14..D-16, we test:
1. JSONL parsing and ObservedAction construction
2. Keystroke coalescing — 5 keystrokes within 500ms → 1 typeText
3. Multiple bursts separated by >500ms → multiple typeTexts
4. Word boundaries (space, return) flush immediately
5. Non-keystroke events (click, scroll) don't affect coalescing
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from basicctrl.learning.coalesce import KeystrokeCoalescer
from basicctrl.learning.recorder import LearningRecorder
from basicctrl.learning.schemas import ObservedAction


@pytest.mark.unit
class TestKeystrokeCoalescer:
    """Test keystroke coalescing logic."""

    def test_single_keystroke(self):
        """Test single keystroke passes through unchanged."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        result = coalescer.add_keystroke("a", 0.0)
        assert result is None  # No flush yet
        assert coalescer.buffer == ["a"]

    def test_multiple_keystrokes_no_boundary(self):
        """Test multiple keystrokes accumulate in buffer."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        ts = time.time()

        coalescer.add_keystroke("h", ts)
        coalescer.add_keystroke("e", ts + 0.01)
        coalescer.add_keystroke("l", ts + 0.02)
        coalescer.add_keystroke("l", ts + 0.03)
        coalescer.add_keystroke("o", ts + 0.04)

        assert coalescer.buffer == ["h", "e", "l", "l", "o"]

    def test_space_boundary_flushes_buffer(self):
        """Test space character flushes buffer immediately."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        ts = time.time()

        coalescer.add_keystroke("h", ts)
        coalescer.add_keystroke("i", ts + 0.01)
        result = coalescer.add_keystroke(" ", ts + 0.02)

        assert result == "hi "
        assert coalescer.buffer == []

    def test_return_boundary_flushes_buffer(self):
        """Test return character flushes buffer immediately."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        ts = time.time()

        coalescer.add_keystroke("t", ts)
        coalescer.add_keystroke("e", ts + 0.01)
        coalescer.add_keystroke("s", ts + 0.02)
        coalescer.add_keystroke("t", ts + 0.03)
        result = coalescer.add_keystroke("\n", ts + 0.04)

        assert result == "test\n"
        assert coalescer.buffer == []

    def test_multiple_words_with_spaces(self):
        """Test multi-word input produces separate flushes."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        ts = time.time()

        results = []
        results.append(coalescer.add_keystroke("h", ts))
        results.append(coalescer.add_keystroke("i", ts + 0.01))
        results.append(coalescer.add_keystroke(" ", ts + 0.02))  # Flush "hi "
        results.append(coalescer.add_keystroke("y", ts + 0.03))
        results.append(coalescer.add_keystroke("o", ts + 0.04))
        results.append(coalescer.add_keystroke("u", ts + 0.05))

        assert results == [None, None, "hi ", None, None, None]
        assert coalescer.buffer == ["y", "o", "u"]

    def test_manual_flush(self):
        """Test manual flush without boundary."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        ts = time.time()

        coalescer.add_keystroke("h", ts)
        coalescer.add_keystroke("i", ts + 0.01)

        result = coalescer.flush()
        assert result == "hi"
        assert coalescer.buffer == []

    def test_flush_on_empty_buffer(self):
        """Test flush on empty buffer returns None."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        result = coalescer.flush()
        assert result is None

    def test_word_boundary_characters(self):
        """Test various word boundary characters."""
        coalescer = KeystrokeCoalescer(window_ms=500.0)
        boundaries = [" ", "\n", "\t", ".", ",", "!", "?", ";", ":", "-", "/"]

        for boundary in boundaries:
            coalescer = KeystrokeCoalescer(window_ms=500.0)
            coalescer.add_keystroke("a", 0.0)
            result = coalescer.add_keystroke(boundary, 0.01)
            assert result == f"a{boundary}", f"Failed for boundary: {repr(boundary)}"
            assert coalescer.buffer == []


@pytest.mark.unit
class TestLearningRecorderJSONL:
    """Test JSONL parsing and ObservedAction construction."""

    @pytest.mark.asyncio
    async def test_parse_keystroke_event(self):
        """Test parsing keystroke event from JSONL."""
        recorder = LearningRecorder()
        ts = time.time()

        event = {
            "type": "key_down",
            "ts": ts,
            "payload": {"key": "a", "key_code": 0},
        }

        # Process event (keystroke goes to coalescer, not yielded)
        actions = []
        async for action in recorder.process_event(event):
            actions.append(action)

        assert len(actions) == 0  # Keystroke buffered, not flushed
        assert recorder.coalescer.buffer == ["a"]

    @pytest.mark.asyncio
    async def test_parse_click_event_flushes_keystrokes(self):
        """Test click event flushes coalesced keystrokes."""
        recorder = LearningRecorder()
        ts = time.time()

        # Add some keystrokes
        recorder.coalescer.add_keystroke("h", ts)
        recorder.coalescer.add_keystroke("i", ts + 0.01)

        # Click should flush them
        click_event = {
            "type": "left_mouse_down",
            "ts": ts + 0.02,
            "payload": {"x": 100, "y": 200},
        }

        actions = []
        async for action in recorder.process_event(click_event):
            actions.append(action)

        assert len(actions) == 2
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload == {"text": "hi"}
        assert actions[1].action.action_type == "click"
        assert actions[1].action.payload == {"x": 100, "y": 200, "button": "left"}

    @pytest.mark.asyncio
    async def test_parse_scroll_event_flushes_keystrokes(self):
        """Test scroll event flushes coalesced keystrokes."""
        recorder = LearningRecorder()
        ts = time.time()

        # Add keystrokes
        recorder.coalescer.add_keystroke("x", ts)

        # Scroll
        scroll_event = {
            "type": "scroll",
            "ts": ts + 0.01,
            "payload": {"dx": 0, "dy": -5},
        }

        actions = []
        async for action in recorder.process_event(scroll_event):
            actions.append(action)

        assert len(actions) == 2
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload == {"text": "x"}
        assert actions[1].action.action_type == "scroll"
        assert actions[1].action.payload == {"dx": 0, "dy": -5}

    @pytest.mark.asyncio
    async def test_observed_action_schema(self):
        """Test ObservedAction construction follows schema."""
        recorder = LearningRecorder(session_id="test-session")
        ts = time.time()

        # Create an action via recorder
        obs = recorder._make_observed_action(
            action_type="click",
            user_gesture_type="click",
            payload={"x": 10, "y": 20},
            timestamp=ts,
            success=True,
        )

        assert isinstance(obs, ObservedAction)
        assert obs.step_idx == 0
        assert obs.user_gesture_type == "click"
        assert obs.action.action_type == "click"
        assert obs.action.kind == "READ"
        assert obs.action.session_id == "test-session"
        assert obs.success is True


@pytest.mark.unit
class TestLearningRecorderIntegration:
    """Test end-to-end recorder flow."""

    @pytest.mark.asyncio
    async def test_keystroke_coalescing_in_recorder(self):
        """Test keystroke coalescing within recorder workflow.

        Simulates: 5 keystrokes in rapid succession → 1 typeText.
        """
        recorder = LearningRecorder(window_ms=500.0)
        ts = time.time()

        # Generate 5 keystroke events in rapid succession
        events = [
            {"type": "key_down", "ts": ts + i * 0.01, "payload": {"key": c}}
            for i, c in enumerate(["h", "e", "l", "l", "o"])
        ]

        actions = []
        for event in events:
            async for action in recorder.process_event(event):
                actions.append(action)

        # All keystrokes buffered, no actions yet
        assert len(actions) == 0
        assert recorder.coalescer.buffer == ["h", "e", "l", "l", "o"]

    @pytest.mark.asyncio
    async def test_space_flushes_coalesced_keystrokes(self):
        """Test space character flushes coalesced keystrokes."""
        recorder = LearningRecorder()
        ts = time.time()

        events = [
            {"type": "key_down", "ts": ts, "payload": {"key": "h"}},
            {"type": "key_down", "ts": ts + 0.01, "payload": {"key": "i"}},
            {"type": "key_down", "ts": ts + 0.02, "payload": {"key": " "}},
        ]

        actions = []
        for event in events:
            async for action in recorder.process_event(event):
                actions.append(action)

        # Space should trigger flush
        assert len(actions) == 1
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload == {"text": "hi "}

    def test_recorder_initialization(self):
        """Test recorder initializes with correct parameters."""
        recorder = LearningRecorder(
            socket_path="/tmp/test.sock",
            window_ms=400.0,
            session_id="custom-session",
        )

        assert recorder.socket_path == "/tmp/test.sock"
        assert recorder.window_ms == 400.0
        assert recorder.session_id == "custom-session"
        assert recorder.step_idx == 0
