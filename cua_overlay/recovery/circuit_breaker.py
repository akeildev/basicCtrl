"""Circuit breaker — prevents cascading recovery on broken targets.

Per CONTEXT.md D-12, D-13: per-(bundle_id, target_key) failure counter. After
3 consecutive failures within a 60s window, trip the breaker: reorder
AppProfile.translator_priority, emit event, prevent auto-heal for 60s.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

from cua_overlay.persist.session_writer import SessionWriter
from cua_overlay.profile.classifier import AppProfile

_log = structlog.get_logger()


class BreakState(BaseModel):
    """State of a circuit breaker for one (bundle_id, target_key)."""

    model_config = ConfigDict(frozen=True)

    bundle_id: str
    target_key: str
    failure_count: int = 0  # incremented on each failure
    tripped_at: Optional[datetime] = None  # None if not tripped; set when count >= 3
    trip_window_start: datetime  # when the first failure in this window occurred


class CircuitBreaker:
    """Per-(bundle_id, target_key) failure counter with 60s window.

    Trip on 3 consecutive failures: reorder translator_priority, emit event,
    prevent auto-heal.
    """

    def __init__(self, session_writer: Optional[SessionWriter] = None):
        """Initialize circuit breaker.

        Args:
            session_writer: SessionWriter for emitting trip events (optional for testing)
        """
        self._session_writer = session_writer
        self._state: dict[str, BreakState] = {}
        self._lock = asyncio.Lock()

    async def record_failure(
        self,
        bundle_id: str,
        target_key: str,
        app_profile: Optional[AppProfile] = None,
    ) -> bool:
        """Record one failure on a target.

        Returns True if breaker just tripped (3rd failure); False otherwise.

        If within 60s window since first failure: increment failure_count.
        If count >= 3: trip the breaker, reorder translator_priority (move
        index 0 to end), emit circuit_breaker_tripped event, return True.
        If 60s elapsed since first failure: reset count to 1, return False.

        Args:
            bundle_id: target app bundle ID
            target_key: composite locator key
            app_profile: AppProfile to reorder (optional; only used on trip)

        Returns:
            True if breaker just tripped (3rd failure); False otherwise
        """
        async with self._lock:
            key = f"{bundle_id}:{target_key}"
            now = datetime.utcnow()

            # Get or create state
            if key not in self._state:
                self._state[key] = BreakState(
                    bundle_id=bundle_id,
                    target_key=target_key,
                    failure_count=1,
                    trip_window_start=now,
                )
                return False

            state = self._state[key]

            # Check if 60s window has expired
            window_elapsed = now - state.trip_window_start
            if window_elapsed.total_seconds() > 60:
                # Reset window
                self._state[key] = BreakState(
                    bundle_id=bundle_id,
                    target_key=target_key,
                    failure_count=1,
                    trip_window_start=now,
                )
                return False

            # Increment failure count
            new_count = state.failure_count + 1

            # Check if we should trip
            if new_count >= 3:
                # Trip the breaker
                tripped_at = now
                self._state[key] = BreakState(
                    bundle_id=bundle_id,
                    target_key=target_key,
                    failure_count=new_count,
                    tripped_at=tripped_at,
                    trip_window_start=state.trip_window_start,
                )

                # Reorder translator_priority if app_profile provided
                if app_profile is not None and len(app_profile.translator_priority) > 0:
                    # Move first element to end
                    priority = app_profile.translator_priority.copy()
                    first = priority.pop(0)
                    priority.append(first)
                    app_profile.translator_priority = priority

                # Emit trip event
                await self._emit_trip_event(bundle_id, target_key, new_count)

                return True

            # Count < 3, just update
            self._state[key] = BreakState(
                bundle_id=bundle_id,
                target_key=target_key,
                failure_count=new_count,
                tripped_at=state.tripped_at,
                trip_window_start=state.trip_window_start,
            )
            return False

    async def is_tripped(self, bundle_id: str, target_key: str) -> bool:
        """Return True if breaker tripped and <60s since trip.

        Args:
            bundle_id: target app bundle ID
            target_key: composite locator key

        Returns:
            True if breaker is currently tripped; False otherwise
        """
        async with self._lock:
            key = f"{bundle_id}:{target_key}"
            if key not in self._state:
                return False

            state = self._state[key]
            if state.tripped_at is None:
                return False

            # Check if 60s has elapsed since trip
            now = datetime.utcnow()
            elapsed = now - state.tripped_at
            return elapsed.total_seconds() <= 60

    async def reset(self, bundle_id: str, target_key: str) -> None:
        """Manually reset state (MCP tool D-25 will call this).

        Args:
            bundle_id: target app bundle ID
            target_key: composite locator key
        """
        async with self._lock:
            key = f"{bundle_id}:{target_key}"
            if key in self._state:
                del self._state[key]
                _log.info(
                    "circuit_breaker.reset",
                    bundle_id=bundle_id,
                    target_key=target_key,
                )

    async def _emit_trip_event(
        self, bundle_id: str, target_key: str, failure_count: int
    ) -> None:
        """Emit structured circuit_breaker_tripped event.

        Args:
            bundle_id: target app bundle ID
            target_key: composite locator key
            failure_count: number of failures before trip
        """
        if self._session_writer is None:
            return

        event = {
            "event": "circuit_breaker_tripped",
            "bundle_id": bundle_id,
            "target_key": target_key,
            "failure_count": failure_count,
            "ts": datetime.utcnow().isoformat(),
        }
        await self._session_writer.append_action_log(event)
        _log.info(
            "circuit_breaker.tripped",
            bundle_id=bundle_id,
            target_key=target_key,
            failure_count=failure_count,
        )
