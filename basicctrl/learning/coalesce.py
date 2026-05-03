"""Keystroke coalescing via CFRunLoopTimer-style 0.5s window.

Per Phase 4 D-14..D-16:

Buffers rapid keystrokes and flushes them as a single typeText action
on timer expiry or word boundary (whitespace/punctuation).

This matches the CFRunLoopTimer(0.5s) behavior described in 04-CONTEXT.md:
- Each keystroke resets the timer.
- Timer fires after 0.5s of no new keystrokes.
- Word boundaries (space, return, punctuation) flush immediately.
- Result: 1 typeText per word instead of N keystroke events.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Optional


class KeystrokeCoalescer:
    """Buffers keystrokes, flushes on timer or word boundary."""

    def __init__(self, window_ms: float = 500.0):
        """Initialize coalescer with 0.5s CFRunLoopTimer window.

        Args:
            window_ms: Time window in milliseconds (default 500 matches CFRunLoopTimer).
        """
        self.window_ms = window_ms
        self.buffer: list[str] = []
        self.last_keystroke_ts: float = 0.0
        self.timer_task: Optional[asyncio.Task[None]] = None
        self._flush_callback: Optional[callable] = None

    def add_keystroke(self, key: str, ts: Optional[float] = None) -> Optional[str]:
        """Add a keystroke to the buffer.

        Args:
            key: The keystroke key as a string (e.g., "a", "A", "Return", etc.)
            ts: Timestamp in seconds since epoch (defaults to now).

        Returns:
            Flushed text if word boundary detected; None otherwise.
        """
        if ts is None:
            ts = time.time()

        # Check for word boundary (space, return, punctuation)
        if self._is_word_boundary(key):
            # Flush current buffer immediately
            flushed = self._flush_impl()
            # Also add the boundary key to output
            if key == "\n":
                return (flushed + "\n") if flushed else "\n"
            elif key == " ":
                return (flushed + " ") if flushed else " "
            else:
                return (flushed + key) if flushed else key

        # Add to buffer and reset timer
        self.buffer.append(key)
        self.last_keystroke_ts = ts

        return None

    def flush(self) -> Optional[str]:
        """Manually flush buffered keystrokes (e.g., on non-keystroke event)."""
        return self._flush_impl()

    async def flush_async(self) -> Optional[str]:
        """Async version of flush."""
        return self._flush_impl()

    def _flush_impl(self) -> Optional[str]:
        """Internal flush implementation."""
        if not self.buffer:
            return None

        text = "".join(self.buffer)
        self.buffer = []
        self.last_keystroke_ts = 0.0

        # Cancel pending timer
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
            self.timer_task = None

        return text

    def _is_word_boundary(self, key: str) -> bool:
        """Check if key is a word boundary.

        Word boundaries: space, return, tab, common punctuation.
        """
        return key in (" ", "\n", "\t", ".", ",", "!", "?", ";", ":", "-", "/")

    def set_flush_callback(self, callback: callable) -> None:
        """Register callback to be called when buffer is flushed.

        Args:
            callback: async function(text: str) or sync function(text: str)
        """
        self._flush_callback = callback

    async def start_timer(self) -> None:
        """Start the CFRunLoopTimer-style async timer.

        Runs in background and flushes buffer after window_ms of inactivity.
        Call this once at startup; it runs indefinitely until cancelled.
        """
        while True:
            try:
                # Wait for buffer to have content
                while not self.buffer:
                    await asyncio.sleep(0.01)

                # Wait for timer to fire (window_ms since last keystroke)
                last_ts = self.last_keystroke_ts
                while True:
                    elapsed = (time.time() - last_ts) * 1000.0
                    if elapsed >= self.window_ms:
                        # Timer fired; flush
                        text = self._flush_impl()
                        if text and self._flush_callback:
                            if inspect.iscoroutinefunction(self._flush_callback):
                                await self._flush_callback(text)
                            else:
                                self._flush_callback(text)
                        break
                    # Sleep a bit and check again
                    await asyncio.sleep(0.01)
                    # If new keystroke came in, reset timer
                    if self.last_keystroke_ts > last_ts:
                        last_ts = self.last_keystroke_ts

            except asyncio.CancelledError:
                # Graceful shutdown
                break

    async def start_timer_task(self) -> None:
        """Start the timer as a background asyncio task."""
        if not self.timer_task or self.timer_task.done():
            self.timer_task = asyncio.create_task(self.start_timer())

    def cancel_timer(self) -> None:
        """Cancel the timer task."""
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
            self.timer_task = None
