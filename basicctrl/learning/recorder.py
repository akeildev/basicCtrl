"""CGEvent tap consumer — JSONL socket reader + ObservedAction builder.

Per Phase 4 D-14..D-15:

Reads JSONL-formatted CGEvent tap events from a Unix socket or stdin.
Converts raw keystroke/click/scroll events to ObservedAction Pydantic models.
Integrates keystroke coalescing via KeystrokeCoalescer.

Typical flow:
1. Swift LearningRecorder.swift writes JSONL to stdout/socket
2. Python LearningRecorder.start() reads lines, parses to dict
3. process_event() converts dict → ObservedAction
4. KeystrokeCoalescer buffers keystrokes, emits 1 typeText per word
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncIterator, Optional

from cua_overlay.learning.coalesce import KeystrokeCoalescer
from cua_overlay.learning.schemas import ObservedAction
from cua_overlay.state.causal_dag import ActionCanonical


class LearningRecorder:
    """CGEvent tap consumer — reads JSONL, builds ObservedAction stream."""

    def __init__(
        self,
        socket_path: str = "/tmp/cua-learning.sock",
        window_ms: float = 500.0,
        session_id: str = "default",
    ):
        """Initialize recorder with socket path and coalescing window.

        Args:
            socket_path: Unix socket path for IPC (default /tmp/cua-learning.sock)
            window_ms: Keystroke coalescing window in ms (default 500)
            session_id: Session ID for ActionCanonical events
        """
        self.socket_path = socket_path
        self.window_ms = window_ms
        self.session_id = session_id
        self.coalescer = KeystrokeCoalescer(window_ms=window_ms)
        self.step_idx = 0
        self.events_queue: asyncio.Queue[ObservedAction] = asyncio.Queue()

        # Register callback to emit coalesced keystrokes
        self.coalescer.set_flush_callback(self._emit_coalesced_keystroke)

    async def start_from_stdin(self) -> AsyncIterator[ObservedAction]:
        """Start reading JSONL events from stdin (for subprocess mode).

        Yields:
            ObservedAction for each event (coalesced keystrokes included).
        """
        # Start timer in background
        timer_task = asyncio.create_task(self.coalescer.start_timer())

        try:
            # Read from stdin line by line
            loop = asyncio.get_event_loop()
            while True:
                line = await loop.run_in_executor(None, self._read_stdin_line)
                if not line:
                    break

                try:
                    event = json.loads(line)
                    async for obs_action in self.process_event(event):
                        yield obs_action
                except json.JSONDecodeError as e:
                    # Skip malformed JSON
                    continue

            # Flush any remaining coalesced keystrokes at end
            final_text = self.coalescer.flush()
            if final_text:
                yield self._make_observed_action(
                    action_type="type",
                    user_gesture_type="keystroke",
                    payload={"text": final_text},
                    timestamp=time.time(),
                    success=True,
                )

        finally:
            timer_task.cancel()
            self.coalescer.cancel_timer()

    async def start_from_socket(self) -> AsyncIterator[ObservedAction]:
        """Start reading JSONL events from Unix socket.

        Yields:
            ObservedAction for each event (coalesced keystrokes included).
        """
        if not os.path.exists(self.socket_path):
            raise FileNotFoundError(f"Socket not found: {self.socket_path}")

        timer_task = asyncio.create_task(self.coalescer.start_timer())

        try:
            # Connect to Unix socket
            reader, writer = await asyncio.open_unix_connection(self.socket_path)

            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=30.0)
                    if not line:
                        break

                    event = json.loads(line.decode("utf-8").strip())
                    async for obs_action in self.process_event(event):
                        yield obs_action

                except asyncio.TimeoutError:
                    # No data received for 30s; connection may be stale
                    break
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue

            # Flush any remaining coalesced keystrokes
            final_text = self.coalescer.flush()
            if final_text:
                yield self._make_observed_action(
                    action_type="type",
                    user_gesture_type="keystroke",
                    payload={"text": final_text},
                    timestamp=time.time(),
                    success=True,
                )

            writer.close()
            await writer.wait_closed()

        finally:
            timer_task.cancel()
            self.coalescer.cancel_timer()

    async def process_event(self, event: dict) -> AsyncIterator[ObservedAction]:
        """Convert CGEvent tap event to ObservedAction.

        Args:
            event: Raw event dict from JSONL (e.g., {"type": "keystroke", ...})

        Yields:
            ObservedAction for non-keystroke events.
            For keystrokes: yields nothing (queued in coalescer).
        """
        event_type = event.get("type")
        payload = event.get("payload", {})
        ts = event.get("ts", time.time())

        if event_type == "key_down":
            # Add to coalescer; may flush on word boundary
            key = payload.get("key", "")
            flushed = self.coalescer.add_keystroke(key, ts)
            if flushed:
                # Word boundary or punctuation flushed buffer
                yield self._make_observed_action(
                    action_type="type",
                    user_gesture_type="keystroke",
                    payload={"text": flushed},
                    timestamp=ts,
                    success=True,
                )

        elif event_type == "key_up":
            # Typically ignored in favor of key_down
            pass

        elif event_type in ("left_mouse_down", "right_mouse_down"):
            # Flush coalesced keystrokes before mouse click
            flushed = self.coalescer.flush()
            if flushed:
                yield self._make_observed_action(
                    action_type="type",
                    user_gesture_type="keystroke",
                    payload={"text": flushed},
                    timestamp=ts,
                    success=True,
                )

            # Emit click event
            x = payload.get("x", 0)
            y = payload.get("y", 0)
            button = "left" if event_type == "left_mouse_down" else "right"

            yield self._make_observed_action(
                action_type="click",
                user_gesture_type="click",
                payload={"x": x, "y": y, "button": button},
                timestamp=ts,
                success=True,
            )

        elif event_type == "scroll":
            # Flush coalesced keystrokes before scroll
            flushed = self.coalescer.flush()
            if flushed:
                yield self._make_observed_action(
                    action_type="type",
                    user_gesture_type="keystroke",
                    payload={"text": flushed},
                    timestamp=ts,
                    success=True,
                )

            # Emit scroll event
            dx = payload.get("dx", 0)
            dy = payload.get("dy", 0)

            yield self._make_observed_action(
                action_type="scroll",
                user_gesture_type="scroll",
                payload={"dx": dx, "dy": dy},
                timestamp=ts,
                success=True,
            )

        elif event_type == "tap_re_enabled":
            # Flush any pending keystrokes
            flushed = self.coalescer.flush()
            if flushed:
                yield self._make_observed_action(
                    action_type="type",
                    user_gesture_type="keystroke",
                    payload={"text": flushed},
                    timestamp=ts,
                    success=True,
                )

    def _make_observed_action(
        self,
        action_type: str,
        user_gesture_type: str,
        payload: dict,
        timestamp: float,
        success: bool,
    ) -> ObservedAction:
        """Create an ObservedAction from raw event."""
        import uuid

        action = ActionCanonical(
            id=str(uuid.uuid4()),
            step_idx=self.step_idx,
            kind="READ",  # Recording is read-only
            target_key="",  # Will be filled by recipe synthesis
            action_type=action_type,
            payload=payload,
            timestamp_ns=int(timestamp * 1e9),
            session_id=self.session_id,
        )

        obs = ObservedAction(
            step_idx=self.step_idx,
            action=action,
            user_gesture_type=user_gesture_type,
            timestamp=timestamp,
            success=success,
        )

        self.step_idx += 1
        return obs

    async def _emit_coalesced_keystroke(self, text: str) -> None:
        """Callback for coalescer to emit buffered keystroke as typeText.

        Args:
            text: Coalesced keystroke text.
        """
        obs = self._make_observed_action(
            action_type="type",
            user_gesture_type="keystroke",
            payload={"text": text},
            timestamp=time.time(),
            success=True,
        )
        await self.events_queue.put(obs)

    def _read_stdin_line(self) -> Optional[str]:
        """Blocking read from stdin (called via executor)."""
        try:
            import sys
            line = sys.stdin.readline()
            return line if line else None
        except EOFError:
            return None
