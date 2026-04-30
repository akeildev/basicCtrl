"""AXUIElementWrapper — high-level façade combining rate limit, cache, typed errors.

Per Pitfall P2 prevention rule 2 (PITFALLS.md):
    Coalesce reads: cache AXUIElement attribute reads with 100ms TTL — same
    composite_key in flight returns the cached value rather than re-querying.

This wrapper is the recommended entry-point for any caller that needs to read
attributes off a single ``AXUIElement`` repeatedly (e.g. verifier polling
``AXValue`` after an action). It serialises three concerns in one place:

1. **Rate limit** — every real read goes through ``TokenBucket.acquire``.
2. **Read cache** — successful reads cached with a 100ms TTL keyed by attribute.
3. **Typed errors** — ``AXUIElementCopyAttributeValue`` failures map to
   ``AXError`` subclasses via ``axerror_from_code``.

Fail-open behaviour: when the bucket is empty, the wrapper returns the last
cached value (even if stale, with a structured warning logging the age) rather
than blocking. If there is no cache entry, it returns ``None``.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from cua_overlay.ax.errors import (
    AXError,
    axerror_from_code,
    kAXErrorAPIDisabled,
    kAXErrorCannotComplete,
    kAXErrorInvalidUIElement,
    kAXErrorNotificationUnsupported,
)
from cua_overlay.ax.rate_limit import TokenBucket

# 100ms read coalescing window per Pitfall P2 prevention rule 2.
_CACHE_TTL_SECONDS = 0.1


class _CachedValue:
    """Tiny holder for cache entries — value + monotonic timestamp."""

    __slots__ = ("value", "ts")

    def __init__(self, value: Any, ts: float) -> None:
        self.value = value
        self.ts = ts


class AXUIElementWrapper:
    """Façade combining rate-limit + 100ms read cache + typed AX errors.

    Construct with the raw ``AXUIElement`` opaque, the owning pid, the bundle_id
    (for log context), and a shared ``TokenBucket`` (one bucket per process is
    correct — the cap is per-pid, not per-element).
    """

    def __init__(
        self,
        ax_element: Any,
        pid: int,
        bundle_id: str,
        bucket: TokenBucket,
    ) -> None:
        self._elem = ax_element
        self.pid = pid
        self.bundle_id = bundle_id
        self._bucket = bucket
        self._cache: dict[str, _CachedValue] = {}
        self._log = structlog.get_logger().bind(pid=pid, bundle_id=bundle_id)

    async def read_attribute(self, attribute: str) -> Any:
        """Read one AX attribute, with cache + rate-limit + typed error mapping.

        Returns the attribute value, ``None`` if the attribute is unsupported,
        or the last-cached value (with a stale-warning log line) when the
        bucket is empty.

        Raises ``AXError`` subclass if the underlying AX call fails with
        ``kAXErrorCannotComplete`` / ``kAXErrorAPIDisabled`` /
        ``kAXErrorInvalidUIElement`` / ``kAXErrorNotificationUnsupported`` —
        these are the codes that signal something the caller cares about.
        """
        # Cache hit?
        cached = self._cache.get(attribute)
        if cached is not None and (time.monotonic() - cached.ts) < _CACHE_TTL_SECONDS:
            return cached.value

        # Bucket gate.
        if not await self._bucket.acquire(self.pid):
            # Fail-open per P2 rule 5: serve last-cached value if any.
            if cached is not None:
                self._log.warning(
                    "ax.served_stale_due_to_rate_limit",
                    attribute=attribute,
                    age_ms=int((time.monotonic() - cached.ts) * 1000),
                )
                return cached.value
            return None

        # Real AX read on a thread so the asyncio loop stays responsive even
        # when AX is slow.
        def _sync() -> Any:
            try:  # pragma: no cover — non-macOS dev hosts skip this
                from HIServices import (  # type: ignore[import-not-found]
                    AXUIElementCopyAttributeValue,
                )
            except ImportError:
                return None
            err, value = AXUIElementCopyAttributeValue(self._elem, attribute, None)
            if err == 0:
                return value
            # The codes we care about — surface as typed exceptions so callers
            # can branch on TCC revoked vs stale ref vs notification unsupported.
            if err in (
                int(kAXErrorCannotComplete),
                int(kAXErrorAPIDisabled),
                int(kAXErrorInvalidUIElement),
                int(kAXErrorNotificationUnsupported),
            ):
                raise axerror_from_code(err, f"AX read failed: {attribute}")
            # Other codes (attribute unsupported, no value, etc.) → caller-
            # benign: return None and let the caller default it.
            return None

        try:
            value = await asyncio.to_thread(_sync)
        except AXError:
            # Don't cache failures — re-try is what the caller wants.
            raise

        self._cache[attribute] = _CachedValue(value=value, ts=time.monotonic())
        return value
