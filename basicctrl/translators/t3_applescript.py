"""T3 AppleScript Translator — py-applescript 1.0.3 in-process NSAppleScript.

Per CONTEXT.md D-04: dedicated ``concurrent.futures.ThreadPoolExecutor(
max_workers=2, thread_name_prefix='cua-as')``. NEVER the fork+exec CLI tool
(50-200ms fork+exec cost; blocks racing budget — see CONTEXT.md D-04 hard rule).

Per RESEARCH.md §"Pattern 6" + Pitfall E (compiled-script caching mandatory —
recompile costs 50-200ms, defeats the racing budget).

T-2-03 mitigation: NSAppleScript on a detached background thread can hang
waiting for AppleEvent reply (``macOS26-Agent/Conversation.swift:245-248``).
The dedicated ThreadPoolExecutor isolates AS calls from the main asyncio
loop AND caps concurrency at 2 (enough for staggered race + parallel
verification call; avoids saturating thread count when AS is slow).

D-14 default channel binding: T3 → C4 (AppleScript channel).
D-15 stagger 500ms: enforced at race orchestrator (Plan 02-10), NOT inside
this module — execute() returns immediately when called.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog

from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.translators.base import TargetSpec, TranslatorTarget


_log = structlog.get_logger()


# Module-level compiled-script cache (Pitfall E mitigation).
# Keyed by source string; values are applescript.AppleScript instances.
# Module-scoped so re-instantiating T3AppleScriptTranslator (e.g. across
# tests) doesn't invalidate compiled scripts.
_compiled_cache: dict[str, Any] = {}
_compiled_lock = threading.Lock()


# Per-bundle AppleScript application names. Default: bundle_id minus
# "com.apple." prefix as app name. Extend as new sdef-bearing apps land
# in known_apps.py (D-21 / D-22).
_APP_NAMES: dict[str, str] = {
    "com.apple.iWork.Pages": "Pages",
    "com.apple.iWork.Numbers": "Numbers",
    "com.apple.iWork.Keynote": "Keynote",
    "com.apple.mail": "Mail",
    "com.apple.iCal": "Calendar",
    "com.apple.Notes": "Notes",
    "com.apple.reminders": "Reminders",
    "com.apple.Safari": "Safari",
    "com.apple.Terminal": "Terminal",
    "com.apple.Music": "Music",
    "com.apple.TextEdit": "TextEdit",
}


class T3AppleScriptTranslator:
    """T3 AppleScript translator. py-applescript on dedicated thread pool.

    Per CONTEXT.md D-04 the executor MUST be dedicated (not asyncio's default
    pool) to isolate AS calls from the main loop and bound concurrency at 2.

    Per CONTEXT.md D-14 the default channel binding is T3 → C4.

    The translator does not "resolve" targets in the AX-tree-walk sense —
    AppleScript addresses targets by name (via ``tell application "..."``
    blocks). ``resolve()`` returns a synthetic ``TranslatorTarget`` whose
    ``as_target_spec`` carries the wrapped tell-block; C4 reads it at fire-time.
    """

    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T3"

    def __init__(self) -> None:
        # D-04 / T-2-03: dedicated max_workers=2 pool; thread_name_prefix for
        # diagnostics + the unit-test assertion that AS runs off the asyncio
        # default executor.
        self._exec: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="cua-as",
            )
        )

    def __del__(self) -> None:
        # Best-effort cleanup; tests / lifecycle owners should call shutdown()
        # explicitly. Catching everything because __del__ during interpreter
        # teardown can hit weird states.
        try:
            self._exec.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass

    def shutdown(self) -> None:
        """Explicit shutdown hook for tests + lifecycle owners."""
        self._exec.shutdown(wait=False)

    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Public accessor — C4AppleScriptChannel reuses this pool to keep
        the T-2-03 isolation property (channel never spins up its own pool)."""
        return self._exec

    def _build_target_spec(self, bundle_id: str, target_spec: TargetSpec) -> str:
        """Build a ``tell application "..."`` block for the target app + verb.

        Returns "" when ``target_spec.as_verb`` is empty (caller should treat
        as "T3 cannot address this target").
        """
        if not target_spec.as_verb:
            return ""
        app_name = _APP_NAMES.get(bundle_id, bundle_id)
        return f'tell application "{app_name}" to {target_spec.as_verb}'

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
    ) -> Optional[TranslatorTarget]:
        """Build a synthetic TranslatorTarget for AppleScript addressing.

        Per CONTEXT.md D-04 + RESEARCH.md §Pattern 6: T3 doesn't walk an AX
        tree — it builds a tell-block from the bundle_id + as_verb hint and
        relies on the target app's AppleScript dictionary to resolve at fire
        time. The returned TranslatorTarget carries a placeholder UIElement
        (so verifier post-fire can populate the actual element via AX subtree
        re-read or push notification).

        Returns None when as_verb is empty (T3 cannot address it).
        """
        spec = self._build_target_spec(bundle_id, target_spec)
        if not spec:
            return None
        now = datetime.now(timezone.utc)
        synthetic_element = UIElement(
            role="AXUnknown",
            role_path=f"AppleScript[{bundle_id}]",
            label=target_spec.label or target_spec.as_verb,
            bbox=Bbox(x=target_spec.x, y=target_spec.y, w=20, h=20),
            pid=pid,
            bundle_id=bundle_id,
            window_id=0,
            discovered_at=now,
            last_seen_at=now,
            source=[Source.APPLESCRIPT],
        )
        return TranslatorTarget(
            element=synthetic_element,
            as_target_spec=spec,
        )

    async def validate(self, target: TranslatorTarget) -> bool:
        """T3 has no analogous live-state probe (Pitfall P5 — AS calls are
        slow, so we don't pre-probe). Treat as valid if the spec is set."""
        return target.as_target_spec is not None and len(target.as_target_spec) > 0

    async def execute(
        self,
        source: str,
        args: tuple = (),
        *,
        timeout_sec: Optional[float] = None,
        retry_on_transient: bool = True,
    ) -> tuple[str, Optional[str]]:
        """Run AppleScript ``source`` on the dedicated thread pool with
        timeout + one transient-error retry (browser-harness §I3).

        Returns a ``(result_str, error_str_or_None)`` tuple. Errors NEVER
        escape — both compile errors and runtime errors are caught and
        returned in the ``error`` slot per the channel contract (channels
        require a non-raising contract from translators).

        Compiled AppleScript instances are cached per ``source`` string
        (Pitfall E — recompile is 50-200ms, defeats the racing budget).

        Per CONTEXT.md D-04: runs on ``self._exec`` (dedicated cua-as pool),
        NOT ``asyncio.to_thread`` which uses the default executor.

        Browser-harness §I3 additions:
          - ``timeout_sec`` bounds each fire so a stalled AppleEvent
            listener can't block the racing budget. Translates to
            ``ae_timeout: <Ns>`` error string on expiry.
          - ``retry_on_transient`` retries ONCE on AppleEvent codes
            -1712 (timeout), -1708, -609, -10000 — the AS-equivalent of
            browser-harness's stale-session re-attach.
        """
        loop = asyncio.get_running_loop()

        def _sync() -> tuple[str, Optional[str]]:
            try:
                import applescript  # py-applescript 1.0.3
            except ImportError:
                return ("", "py-applescript module unavailable")
            with _compiled_lock:
                scpt = _compiled_cache.get(source)
                if scpt is None:
                    try:
                        scpt = applescript.AppleScript(source=source)
                    except Exception as exc:  # noqa: BLE001 — compile errors caught
                        return ("", f"compile_error: {exc}")
                    _compiled_cache[source] = scpt
            try:
                result = scpt.run(*args)
                return (str(result) if result is not None else "", None)
            except Exception as exc:  # noqa: BLE001 — AppleEvent / runtime errors
                return ("", f"runtime_error: {exc}")

        async def _attempt() -> tuple[str, Optional[str]]:
            # D-04 / T-2-03: dedicated executor, NOT loop's default. This is
            # the whole point of the class — never let AS calls leak onto
            # the main asyncio loop's worker threads where they could
            # starve other tasks or pile up if the target app's
            # AppleEvent listener stalls.
            return await loop.run_in_executor(self._exec, _sync)

        from basicctrl.translators.as_daemon import (
            run_with_resilience,
            _DEFAULT_TIMEOUT_SEC,
        )

        return await run_with_resilience(
            _attempt,
            timeout_sec=timeout_sec if timeout_sec is not None else _DEFAULT_TIMEOUT_SEC,
            retry_on_transient=retry_on_transient,
        )
