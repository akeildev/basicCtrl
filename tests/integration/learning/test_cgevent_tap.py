"""Integration tests for CGEvent tap + coalescing.

Per Phase 4 D-27: Integration test that exercises the full tap + coalescing
pipeline. Tests actual keystroke coalescing behavior with simulated events.

Note: Full integration with the Swift LearningRecorder binary would require
running the binary as a subprocess with mocked events. This test focuses on
the Python consumer side with synthetic JSONL input.
"""
import asyncio
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cua_overlay.learning.coalesce import KeystrokeCoalescer
from cua_overlay.learning.recorder import LearningRecorder


@pytest.mark.integration
class TestCGEventTapPipeline:
    """Integration tests for CGEvent tap + recorder + coalescer."""

    @pytest.mark.asyncio
    async def test_full_keystroke_coalescing_pipeline(self):
        """Test full pipeline: 5 rapid keystrokes → 1 typeText event.

        Scenario: User types "hello" very quickly (all within 500ms window).
        Expected: Single ObservedAction with action_type='type' and text='hello'.
        """
        recorder = LearningRecorder(window_ms=500.0)
        ts = time.time()

        # Simulate 5 rapid keystrokes (all within 100ms total)
        keystroke_events = [
            {"type": "key_down", "ts": ts + 0.001 * i, "payload": {"key": c}}
            for i, c in enumerate(["h", "e", "l", "l", "o"])
        ]

        # Process all keystrokes
        for event in keystroke_events:
            async for _ in recorder.process_event(event):
                pass

        # Manually flush (since we're not using the timer)
        flushed = recorder.coalescer.flush()
        assert flushed == "hello"

    @pytest.mark.asyncio
    async def test_space_boundary_immediate_flush(self):
        """Test that space character causes immediate flush.

        Scenario: User types "hi ", very fast.
        Expected: When space is typed, buffer flushes to single typeText.
        """
        recorder = LearningRecorder()
        ts = time.time()

        # Type "hi" then space
        events = [
            {"type": "key_down", "ts": ts, "payload": {"key": "h"}},
            {"type": "key_down", "ts": ts + 0.01, "payload": {"key": "i"}},
            {"type": "key_down", "ts": ts + 0.02, "payload": {"key": " "}},
        ]

        actions = []
        for event in events:
            async for action in recorder.process_event(event):
                actions.append(action)

        # Space should trigger immediate flush
        assert len(actions) == 1
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload["text"] == "hi "

    @pytest.mark.asyncio
    async def test_multiple_bursts_separate_actions(self):
        """Test multiple burst separated by pause produce separate actions.

        Scenario: User types "hi" + pause > 500ms + types "bye"
        Expected: Two separate typeText actions.
        """
        recorder = LearningRecorder(window_ms=500.0)
        ts = time.time()

        # First burst: "hi"
        burst1_events = [
            {"type": "key_down", "ts": ts + 0.01 * i, "payload": {"key": c}}
            for i, c in enumerate(["h", "i"])
        ]

        # Manually add to coalescer and flush
        for event in burst1_events:
            async for _ in recorder.process_event(event):
                pass

        flushed1 = recorder.coalescer.flush()
        assert flushed1 == "hi"

        # Advance time significantly (> 500ms)
        ts2 = ts + 1.0

        # Second burst: "bye"
        burst2_events = [
            {"type": "key_down", "ts": ts2 + 0.01 * i, "payload": {"key": c}}
            for i, c in enumerate(["b", "y", "e"])
        ]

        for event in burst2_events:
            async for _ in recorder.process_event(event):
                pass

        flushed2 = recorder.coalescer.flush()
        assert flushed2 == "bye"

    @pytest.mark.asyncio
    async def test_click_interrupts_typing_chain(self):
        """Test that click interrupts and flushes keystroke buffer.

        Scenario: User types "hel" then clicks.
        Expected: Keystrokes flush on click; then click action emitted.
        """
        recorder = LearningRecorder()
        ts = time.time()

        # Type "hel"
        type_events = [
            {"type": "key_down", "ts": ts + 0.01 * i, "payload": {"key": c}}
            for i, c in enumerate(["h", "e", "l"])
        ]

        for event in type_events:
            async for _ in recorder.process_event(event):
                pass

        assert recorder.coalescer.buffer == ["h", "e", "l"]

        # Click
        click_event = {
            "type": "left_mouse_down",
            "ts": ts + 0.05,
            "payload": {"x": 100, "y": 200},
        }

        actions = []
        async for action in recorder.process_event(click_event):
            actions.append(action)

        # Should have flushed keystrokes + emitted click
        assert len(actions) == 2
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload["text"] == "hel"
        assert actions[1].action.action_type == "click"
        assert recorder.coalescer.buffer == []

    @pytest.mark.asyncio
    async def test_scroll_interrupts_typing_chain(self):
        """Test that scroll interrupts and flushes keystroke buffer."""
        recorder = LearningRecorder()
        ts = time.time()

        # Type "x"
        type_event = {"type": "key_down", "ts": ts, "payload": {"key": "x"}}
        async for _ in recorder.process_event(type_event):
            pass

        assert recorder.coalescer.buffer == ["x"]

        # Scroll
        scroll_event = {
            "type": "scroll",
            "ts": ts + 0.01,
            "payload": {"dx": 0, "dy": -10},
        }

        actions = []
        async for action in recorder.process_event(scroll_event):
            actions.append(action)

        # Should have flushed keystrokes + emitted scroll
        assert len(actions) == 2
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload["text"] == "x"
        assert actions[1].action.action_type == "scroll"
        assert actions[1].action.payload["dy"] == -10

    @pytest.mark.asyncio
    async def test_tap_re_enabled_flushes_buffer(self):
        """Test tap_re_enabled event flushes buffered keystrokes."""
        recorder = LearningRecorder()
        ts = time.time()

        # Add keystrokes
        recorder.coalescer.add_keystroke("a", ts)

        # Tap re-enabled
        tap_event = {
            "type": "tap_re_enabled",
            "ts": ts + 0.01,
            "payload": {},
        }

        actions = []
        async for action in recorder.process_event(tap_event):
            actions.append(action)

        # Should have flushed buffered keystroke
        assert len(actions) == 1
        assert actions[0].action.action_type == "type"
        assert actions[0].action.payload["text"] == "a"

    @pytest.mark.asyncio
    async def test_coalescer_timer_async(self):
        """Test coalescer timer fires after window_ms of inactivity.

        This is a light integration test of the async timer mechanism.
        """
        coalescer = KeystrokeCoalescer(window_ms=50.0)  # 50ms for fast test
        flushed_texts = []

        async def collect_flushes(text: str) -> None:
            flushed_texts.append(text)

        coalescer.set_flush_callback(collect_flushes)

        # Start timer
        timer_task = asyncio.create_task(coalescer.start_timer())

        try:
            # Add keystroke
            ts = time.time()
            coalescer.add_keystroke("t", ts)
            coalescer.add_keystroke("e", ts + 0.01)
            coalescer.add_keystroke("s", ts + 0.02)
            coalescer.add_keystroke("t", ts + 0.03)

            # Wait for timer to fire (window_ms + some margin)
            await asyncio.sleep(0.15)

            # Timer should have flushed
            assert "test" in flushed_texts

        finally:
            timer_task.cancel()
            try:
                await timer_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_step_idx_increments(self):
        """Test that step_idx increments for each action."""
        recorder = LearningRecorder()
        ts = time.time()

        actions = []

        # First click
        event1 = {
            "type": "left_mouse_down",
            "ts": ts,
            "payload": {"x": 10, "y": 20},
        }
        async for action in recorder.process_event(event1):
            actions.append(action)

        # Second click
        event2 = {
            "type": "left_mouse_down",
            "ts": ts + 0.01,
            "payload": {"x": 30, "y": 40},
        }
        async for action in recorder.process_event(event2):
            actions.append(action)

        assert len(actions) == 2
        assert actions[0].step_idx == 0
        assert actions[1].step_idx == 1
