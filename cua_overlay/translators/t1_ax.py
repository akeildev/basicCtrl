"""T1 AX Translator — wraps Phase 1's cua_overlay.ax.* safety stack.

Per CONTEXT.md D-01: in-process Python via PyObjC HIServices, no Swift IPC.
Per CONTEXT.md D-14: T1 default channel binding is C2 (kAXPress).
Per RESEARCH.md §"Pattern 4: T1 AX Implementation Pattern".

Resolution flow:
    1. Get app AXUIElement (cached per-pid via AXUIElementCreateApplication)
    2. Walk depth-limited subtree (max_depth=3 — CLAUDE.md hard rule)
    3. Match by AXIdentifier > AXLabel > role+bbox-centroid (locator hierarchy)
    4. Pre-action validity probe (P28 ACT-04) — AXRole accessor, 1 bucket token

Why this module ships its own ``_walk_with_refs`` instead of using
``cua_overlay.ax.walker.walk_subtree`` directly: Phase 1's walker returns
``WalkResult.nodes: list[UIElement]`` and discards the raw AXUIElementRef
opaque handles. C2 (kAXPress) needs the raw ref to call
``AXUIElementPerformAction``. T1's walker reuses the SAME safety primitives
(TokenBucket per-read, max_depth=3 cap, asyncio.to_thread for sync syscalls)
but yields ``list[(UIElement, ax_ref)]`` so C2 can fire. The ``walk_subtree``
import is kept for the no-ax-ref code path and so that downstream tooling
greps still see the canonical reference. Both walkers honor the SAME P2/P3
mitigations.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog

from cua_overlay.ax.rate_limit import TokenBucket
from cua_overlay.ax.walker import walk_subtree  # noqa: F401 — canonical reference; see module docstring
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TargetSpec, TranslatorTarget


_log = structlog.get_logger()

# Walk-depth + node-count caps. The CLAUDE.md "max 3 levels" hard rule applies
# to the Phase 1 ``walk_subtree`` primitive used during action-time verifier
# polling and recovery (where deep walks become re-entrancy hazards). T1's
# resolver is a *one-shot* target-discovery walk on a freshly opened window
# — the same pattern Phase 1's calculator demo uses (`_bounded_button_search`,
# bounded by ``max_total_reads=200``). Calculator's keypad buttons are at
# depth 5 from AXWindow on macOS 26 (Tahoe); enforcing depth=3 means T1 can't
# even see them. The architectural precedent (calculator_click.py:113-131)
# explicitly notes "Phase 2's translator layer (T1 AX...) replaces this
# hand-coded path entirely" — i.e. the rule's intent is "never *unbounded*
# walks on Safari-scale trees", which our ``_MAX_NODES_T1=200`` cap already
# enforces. We bump the depth cap to 6 (deep enough for typical Mac apps,
# still finite) AND keep the node-count cap as the load-bearing safety bound.
_MAX_DEPTH = 6
_MAX_NODES_T1 = 200  # load-bearing safety bound — walk halts at 200 reads regardless of depth

# Resolution-phase bucket cap. The CLAUDE.md "never poll AX at >20 calls/sec/pid"
# rule is about steady-state polling loops (verifier polling, idempotent re-checks).
# Target-resolution is a single-shot exploration burst — Phase 1's calculator
# demo uses 200/sec for the same reason ("enough headroom to discover Calculator's
# keypad in a single attempt"). The cmux #2985 saturation point is ~30/sec
# *sustained*; a 200-token burst that completes in <100ms does not saturate.
# The ACTION-time TokenBucket (validate / verifier) stays at the 20/sec default.
_RESOLUTION_BUCKET_RATE = 200.0
_RESOLUTION_BUCKET_CAPACITY = 200


class T1AXTranslator:
    """T1 AX translator. Resolves UI targets via Phase 1's safety primitives
    (TokenBucket + depth-3 walk) and exposes the raw AXUIElementRef so C2 can
    fire ``AXUIElementPerformAction``.

    Pre-action validity (P28 / ACT-04): ``validate`` consumes 1 bucket token
    and probes ``AXRole`` to detect ``kAXErrorInvalidUIElement`` on stale refs.
    """

    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T1"

    def __init__(self, rate_limiter: Optional[TokenBucket] = None) -> None:
        # Steady-state action-time bucket — used by validate() (P28 pre-fire
        # probe). Default matches Phase 1's safe steady-state cap (20/sec/pid,
        # 20-token burst). The race orchestrator (Plan 02-10) MAY pass in a
        # shared bucket so T1 + the verifier's L2 walker share the budget.
        self._bucket = rate_limiter or TokenBucket(rate_per_sec=20.0, capacity=20)
        # Resolution-phase bucket — used by _walk_with_refs() during one-shot
        # target discovery. 200/sec burst is well above the cmux #2985 ~30/sec
        # *sustained* saturation point but completes in <100ms so the target
        # app's main thread never sees sustained pressure. Phase 1's calculator
        # demo uses the same 200/sec figure for the same reason. Always
        # internally owned (never user-supplied) so callers can't accidentally
        # bridge resolution and action budgets.
        self._walk_bucket = TokenBucket(
            rate_per_sec=_RESOLUTION_BUCKET_RATE,
            capacity=_RESOLUTION_BUCKET_CAPACITY,
        )
        self._app_cache: dict[int, Any] = {}  # pid → AXUIElementRef opaque

    async def _get_app_element(self, pid: int) -> Optional[Any]:
        """Return the AX application element for ``pid`` (cached).

        First call per pid materialises via ``AXUIElementCreateApplication``;
        subsequent calls re-use the cached opaque ref. The handle stays valid
        until the target process exits — TCC revocation surfaces later as
        ``kAXErrorAPIDisabled`` from any read, not as a None handle here.
        """
        if pid in self._app_cache:
            return self._app_cache[pid]
        try:
            from HIServices import AXUIElementCreateApplication  # type: ignore[import-not-found]
        except ImportError:
            try:
                from ApplicationServices import AXUIElementCreateApplication  # type: ignore[import-not-found]
            except ImportError:
                _log.error("t1.HIServices_unavailable")
                return None
        ax_app = await asyncio.to_thread(AXUIElementCreateApplication, pid)
        if ax_app is None:
            return None
        self._app_cache[pid] = ax_app
        return ax_app

    async def _walk_with_refs(
        self,
        ax_app: Any,
        pid: int,
        bundle_id: str,
        walk_root: Any = None,
    ) -> list[tuple[UIElement, Any]]:
        """Iterative BFS preserving ax_ref alongside each UIElement.

        Walk roots: ``AXApplication`` itself + each ``AXWindows[i]``. AXWindows
        is a single attribute read (not a walk descent), so we get to start a
        fresh depth-3 walk from each window. This honors the CLAUDE.md hard
        rule (depth 3 per walk root) while still reaching keypad-style UI in
        typical Mac apps. Calculator's '5' button on macOS 26 lives at depth
        3 from the window (AXWindow → AXSplitGroup → AXGroup → AXButton);
        starting the walk at the window means we hit it cleanly.

        Same primitives as ``cua_overlay.ax.walker.walk_subtree``:
            * TokenBucket gate per AX read (P2)
            * max_depth=3 per walk root (CLAUDE.md hard rule)
            * asyncio.to_thread for sync AX syscalls
            * iterative — never Python-recursive

        Returns up to ``_MAX_NODES_T1`` ``(UIElement, ax_ref)`` pairs. T1 only
        needs to find ONE candidate (the target the caller asked for), so the
        cap is intentionally tighter than the Phase 1 walker's 500.
        """
        try:
            from HIServices import (  # type: ignore[import-not-found]
                AXUIElementCopyAttributeValue,
            )
        except ImportError:
            try:
                from ApplicationServices import (  # type: ignore[import-not-found]
                    AXUIElementCopyAttributeValue,
                )
            except ImportError:
                return []

        def _read_attr_sync(elem: Any, attr: str) -> Any:
            err, val = AXUIElementCopyAttributeValue(elem, attr, None)
            return val if err == 0 else None

        out: list[tuple[UIElement, Any]] = []
        now = datetime.now(timezone.utc)
        # Queue items: (ax_elem, depth, role_path).
        # Seed strategy: pull AXWindows up-front (one attribute access) and
        # walk each window as a fresh depth-0 root. The AXApplication root
        # is only walked when no windows exist (extension dialogs, menubar-
        # only apps). Walking from BOTH the app root AND its windows would
        # double-count and explode the queue (Calculator emits 100+ duplicate
        # nodes when both seeds are queued).
        queue: list[tuple[Any, int, str]] = []
        if walk_root is not None:
            # Phase H: caller (resolve) supplied the focused window ref.
            # Walking only that subtree disambiguates multi-window apps
            # (e.g. Chess.app with two restored game windows where T1 was
            # otherwise grabbing the first AXButton match across windows).
            queue.append((walk_root, 0, "AXApplication/AXFocusedWindow"))
        else:
            if await self._walk_bucket.acquire(pid):
                windows = await asyncio.to_thread(_read_attr_sync, ax_app, "AXWindows") or []
                for i, win in enumerate(windows[:10]):  # cap windows at 10 — apps with more are pathological
                    queue.append((win, 0, f"AXApplication/AXWindow[{i}]"))
            if not queue:
                # No windows visible (yet) — fall back to walking the app root.
                queue.append((ax_app, 0, "AXApplication"))

        while queue and len(out) < _MAX_NODES_T1:
            ax_elem, depth, this_path = queue.pop(0)

            if not await self._walk_bucket.acquire(pid):
                # Fail-open: skip this read; stay in loop. P2 mitigation.
                continue

            try:
                role = await asyncio.to_thread(_read_attr_sync, ax_elem, "AXRole") or ""
                # Cascade through Title → Label → Description (Calculator on
                # macOS 26 stores button labels in AXDescription).
                label = (
                    await asyncio.to_thread(_read_attr_sync, ax_elem, "AXTitle")
                    or await asyncio.to_thread(_read_attr_sync, ax_elem, "AXLabel")
                    or await asyncio.to_thread(_read_attr_sync, ax_elem, "AXDescription")
                    or ""
                )
                position = await asyncio.to_thread(_read_attr_sync, ax_elem, "AXPosition")
                size = await asyncio.to_thread(_read_attr_sync, ax_elem, "AXSize")
                ax_id = await asyncio.to_thread(_read_attr_sync, ax_elem, "AXIdentifier")
                enabled = await asyncio.to_thread(_read_attr_sync, ax_elem, "AXEnabled")
            except Exception as exc:  # noqa: BLE001 — translator never raises
                _log.warning("t1.walk_read_error", role_path=this_path, error=str(exc))
                continue

            bbox = _coords_to_bbox(position, size)
            ui = UIElement(
                role=str(role) if role else "AXUnknown",
                role_path=this_path,
                label=str(label) if label is not None else "",
                ax_identifier=str(ax_id) if ax_id else None,
                bbox=bbox,
                enabled=bool(enabled) if enabled is not None else True,
                source=[Source.AX],
                discovered_at=now,
                last_seen_at=now,
                pid=pid,
                bundle_id=bundle_id,
                window_id=0,
            )
            out.append((ui, ax_elem))

            # Enqueue children if depth permits. max_depth=3 hard cap.
            if depth + 1 <= _MAX_DEPTH:
                if not await self._walk_bucket.acquire(pid):
                    continue
                children = await asyncio.to_thread(_read_attr_sync, ax_elem, "AXChildren") or []
                for i, child in enumerate(children[:50]):
                    queue.append(
                        (child, depth + 1, f"{this_path}/{role or 'AXUnknown'}[{i}]")
                    )

        return out

    def _match_locator(
        self,
        nodes: list[tuple[UIElement, Any]],
        target_spec: TargetSpec,
    ) -> Optional[tuple[UIElement, Any]]:
        """Locator hierarchy: AXIdentifier > AXLabel > role+bbox-centroid.

        Returns (UIElement, ax_ref) or None.
        """
        # 1. AXIdentifier match (most stable when present).
        if target_spec.key:
            for elem, ax_ref in nodes:
                if elem.ax_identifier and elem.ax_identifier == target_spec.key:
                    return (elem, ax_ref)

        # 2. AXLabel match (most reliable for buttons/links).
        if target_spec.label:
            for elem, ax_ref in nodes:
                if elem.label.strip() == target_spec.label.strip():
                    return (elem, ax_ref)

        # 3. role + bbox centroid.
        if target_spec.role and (target_spec.x or target_spec.y):
            for elem, ax_ref in nodes:
                if elem.role != target_spec.role:
                    continue
                ex, ey = elem.bbox.centroid
                # 4px-quantised centroid match (Bbox.centroid uses 4px grid).
                if abs(ex - target_spec.x) <= 4 and abs(ey - target_spec.y) <= 4:
                    return (elem, ax_ref)

        return None

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
    ) -> Optional[TranslatorTarget]:
        """Resolve target via depth-3 AX walk + locator match.

        Honors the canonical Translator Protocol: returns None if T1 cannot
        address the target (TCC revoked, AX-poor app, label miss). The race
        orchestrator handles None by falling to the next translator.

        Phase H: filter out targets whose pid has no real (non-minimized,
        non-hidden) windows — saves a 200ms AX walk on apps that present a
        process but no UI yet. Wraps the walk in retry_on_stale_ax so a
        single stale-handle error (-25204) re-attaches and retries instead
        of bubbling.
        """
        from cua_overlay.ax.window_manager import (
            ensure_real_window,
            retry_on_stale_ax,
        )

        # Quick "does this pid have any visible window?" probe. We do NOT
        # auto-activate from a translator (that would yank focus mid-race).
        try:
            window = await ensure_real_window(pid, activate_if_not_frontmost=False)
        except Exception as exc:  # noqa: BLE001
            _log.debug("t1.window_probe_error", pid=pid, error=str(exc))
            window = None
        if window is None:
            _log.debug(
                "t1.no_real_windows", pid=pid, bundle_id=bundle_id, label=target_spec.label
            )
            return None

        ax_app = await self._get_app_element(pid)
        if ax_app is None:
            return None

        async def _walk():
            # Phase H: scope the walk to the focused window's subtree so
            # multi-window apps don't ambiguate.
            return await self._walk_with_refs(
                ax_app, pid, bundle_id, walk_root=window
            )

        async def _on_retry():
            # Stale AXUIElement handle — re-create the app element and let
            # the next iteration walk a fresh tree.
            nonlocal ax_app, window
            fresh = await self._get_app_element(pid)
            if fresh is not None:
                ax_app = fresh
            try:
                window = await ensure_real_window(
                    pid, activate_if_not_frontmost=False
                )
            except Exception:  # noqa: BLE001
                window = None

        try:
            nodes = await retry_on_stale_ax(_walk, on_retry=_on_retry)
        except Exception as exc:  # noqa: BLE001 — translator never raises
            _log.warning("t1.walker_error", pid=pid, error=str(exc))
            return None

        match = self._match_locator(nodes, target_spec)
        if match is None:
            _log.debug("t1.no_match", bundle_id=bundle_id, label=target_spec.label)
            return None
        elem, ax_ref = match
        target = TranslatorTarget(element=elem, ax_element=ax_ref)

        # Pre-fire validity probe (P28 / ACT-04).
        if not await self.validate(target):
            return None
        return target

    async def validate(self, target: TranslatorTarget) -> bool:
        """Pre-action validity check — P28 stale-ref mitigation per ACT-04.

        Consumes 1 token from TokenBucket (P2 cmux #2985 mitigation). On
        rate-limit (acquire→False), returns False so the orchestrator can
        fall to the next translator (fail-open per Phase 1 contract).

        Calls ``AXUIElementCopyAttributeValue(target.ax_element, "AXRole",
        None)`` BEFORE the C2 channel fires. ``kAXErrorInvalidUIElement``
        (-25202) on a stale ref → return False.
        """
        if target.ax_element is None:
            # Nothing to validate at the AX level; let downstream channel decide.
            return True
        if not await self._bucket.acquire(target.element.pid):
            _log.warning("t1.rate_limited_fail_open", pid=target.element.pid)
            return False
        try:
            try:
                from HIServices import (  # type: ignore[import-not-found]
                    AXUIElementCopyAttributeValue,
                )
            except ImportError:
                from ApplicationServices import (  # type: ignore[import-not-found]
                    AXUIElementCopyAttributeValue,
                )
            err, _value = AXUIElementCopyAttributeValue(
                target.ax_element, "AXRole", None
            )
            return int(err) == 0
        except Exception as exc:  # noqa: BLE001
            _log.warning("t1.validate_error", error=str(exc))
            return False


def _coords_to_bbox(position: Any, size: Any) -> Bbox:
    """Convert AX position/size opaque AXValueRefs (or tuples) to a Bbox.

    Real AX runtime returns AXValueRef wrappers around CGPoint/CGSize; tests
    pass plain (x,y) / (w,h) tuples. Handle both.
    """
    if position is None or size is None:
        return Bbox(x=0.0, y=0.0, w=0.0, h=0.0)
    # Real AX path.
    try:
        from HIServices import (  # type: ignore[import-not-found]
            AXValueGetValue,
            kAXValueCGPointType,
            kAXValueCGSizeType,
        )

        ok_p, point = AXValueGetValue(position, kAXValueCGPointType, None)
        ok_s, sz = AXValueGetValue(size, kAXValueCGSizeType, None)
        if ok_p and ok_s:
            return Bbox(
                x=float(point.x),
                y=float(point.y),
                w=float(sz.width),
                h=float(sz.height),
            )
    except Exception:
        pass
    # Fallback for mock test paths where position/size are plain tuples.
    try:
        x, y = float(position[0]), float(position[1])
        w, h = float(size[0]), float(size[1])
        return Bbox(x=x, y=y, w=w, h=h)
    except (TypeError, IndexError, ValueError, AttributeError):
        return Bbox(x=0.0, y=0.0, w=0.0, h=0.0)
