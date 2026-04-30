"""Phase 1 Calculator click end-to-end demo.

The single coroutine that wires every Plan 01-08 component together to prove
the six ROADMAP Phase 1 success criteria:

1. Click in Calculator fires ``kAXValueChanged`` and is recorded as VERIFIED
   in <50ms via L0 push subscription (subscribed BEFORE action fires).
2. State graph round-trips: probe Calculator's "5" button, upsert into
   StateGraph, read back via composite_key.
3. AppProfile classifier caches per-bundle capability probe and survives
   session restart (the on-disk JSON appears at ``~/.cua/profiles/``).
4. L0 push + L1 cheap diff verifies the click in <50ms with no AX subtree
   walk — L2 and L3 must NEVER fire on this path.
5. AX rate-limiter (TokenBucket 20/sec/pid) and depth-limited walker (max
   3) are exercised by the probe path.
6. The healing wrapper / MCP proxy surface (Plan 08) remains importable.

Public surface
--------------

* ``run_demo() -> dict`` — testable core coroutine. Returns a result dict
  (shape locked in PLAN.md Task 1). Pytest tests call this directly.
* ``main() -> int`` — thin CLI wrapper; pretty-prints with ``rich`` and
  returns an exit code (0 on success, 1 on AssertionError caught from
  ``run_demo``).

Run
---

.. code-block:: bash

   uv run python -m cua_overlay.demo.calculator_click

Prerequisites: Calculator launchable, Accessibility TCC granted to the
Python interpreter, Postgres listening (optional — checkpoint failures
degrade to a warning rather than an abort).

Phase 2 will replace the raw ``CGEventCreateMouseEvent`` fire path with the
C1-C5 channel registry; for now we use the bare CGEvent API to exercise the
verifier without a translator layer.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import structlog
from rich.console import Console

from cua_overlay.ax import (
    TokenBucket,
    has_blocking_modal,
    walk_subtree,
)
from cua_overlay.ax.observer import AXEventBridge
from cua_overlay.log import configure as configure_logging
from cua_overlay.persist import DurableExecutor, SessionWriter
from cua_overlay.profile import classify
from cua_overlay.state import StateGraph, UIElement
from cua_overlay.state.causal_dag import ActionCanonical, HoarePre
from cua_overlay.verifier import (
    Aggregator,
    AXObserverManager,
    KqueueProcObserver,
    L0Push,
    L1Cheap,
    L2Medium,
    L3Stub,
    NSWorkspaceObserver,
    VERIFIED_THRESHOLD,
    WeightedVote,
)

# Calculator's actual bundle id is lowercase 'c' (verified via PlistBuddy in
# Plan 02). NSWorkspace runningApplications reports the same.
_CALCULATOR_BUNDLE = "com.apple.calculator"
_CALCULATOR_LAUNCH_TIMEOUT_S = 5.0
_CALCULATOR_AX_READY_TIMEOUT_S = 10.0


def _launch_calculator() -> int:
    """Open Calculator.app via ``open -a`` and return its pid.

    Polls NSWorkspace.runningApplications for the bundle id with a 5s deadline.
    Raises RuntimeError if the app fails to register.
    """
    subprocess.run(["open", "-a", "Calculator"], check=True)

    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover — non-macOS dev hosts
        raise RuntimeError(f"AppKit unavailable: {e}")

    deadline = time.monotonic() + _CALCULATOR_LAUNCH_TIMEOUT_S
    while time.monotonic() < deadline:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if app.bundleIdentifier() == _CALCULATOR_BUNDLE:
                return int(app.processIdentifier())
        time.sleep(0.1)
    raise RuntimeError(
        f"Calculator.app did not register with NSWorkspace within "
        f"{_CALCULATOR_LAUNCH_TIMEOUT_S}s"
    )


async def _find_button5(pid: int, bundle_id: str) -> tuple[UIElement, Any]:
    """Locate Calculator's "5" button via a depth-limited AX walk.

    Returns (UIElement, raw AX child ref). Both are needed: the typed
    ``UIElement`` flows into the StateGraph + Aggregator; the opaque AX ref
    is what AXObserver subscribes against.

    Polls up to 10s while Calculator finishes painting its keypad — a freshly
    launched app may not have the keypad visible immediately.
    """
    try:
        from HIServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
        )
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(f"HIServices unavailable: {e}")

    app = await asyncio.to_thread(AXUIElementCreateApplication, pid)
    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)

    deadline = time.monotonic() + _CALCULATOR_AX_READY_TIMEOUT_S
    last_walk_size = 0
    while time.monotonic() < deadline:
        # Walk one window at a time to stay inside default caps.
        result = await walk_subtree(
            app,
            pid=pid,
            bundle_id=bundle_id,
            bucket=bucket,
        )
        last_walk_size = len(result.nodes)
        match = _select_button5(result.nodes)
        if match is not None:
            # Re-locate the AX ref by index path within the live tree.
            ax_ref = await _resolve_ax_ref(app, match.role_path)
            return match, ax_ref
        await asyncio.sleep(0.25)

    raise RuntimeError(
        f"Calculator '5' button not found after {_CALCULATOR_AX_READY_TIMEOUT_S}s "
        f"(walked {last_walk_size} nodes — keypad may be hidden)"
    )


def _select_button5(nodes: list[UIElement]) -> Optional[UIElement]:
    """Find the AXButton labelled '5' (Calculator localises; accept variants)."""
    accept_labels = {"5", "Five"}
    for n in nodes:
        if n.role != "AXButton":
            continue
        if n.label.strip() in accept_labels:
            return n
    # Fallback: AX may expose the label via AXValue / AXDescription instead of
    # AXTitle on some Calculator builds. Scan value too.
    for n in nodes:
        if n.role != "AXButton":
            continue
        if n.value and n.value.strip() in accept_labels:
            return n
    return None


async def _resolve_ax_ref(app_ref: Any, role_path: str) -> Any:
    """Walk the live AX tree to the element identified by ``role_path``.

    ``role_path`` looks like ``AXApplication/AXWindow[0]/AXGroup[0]/AXButton[7]``.
    We split on '/' and follow ``AXChildren`` indices.
    """
    try:
        from HIServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
        )
    except ImportError:  # pragma: no cover
        return app_ref

    parts = role_path.split("/")
    # First segment is the application root; skip it.
    current = app_ref
    for segment in parts[1:]:
        # segment is e.g. "AXButton[7]" — extract the index.
        if "[" not in segment or not segment.endswith("]"):
            return current
        idx_str = segment.split("[", 1)[1][:-1]
        try:
            idx = int(idx_str)
        except ValueError:
            return current

        def _read_children(elem: Any) -> Any:
            err, children = AXUIElementCopyAttributeValue(elem, "AXChildren", None)
            if err != 0 or children is None:
                return None
            return children

        children = await asyncio.to_thread(_read_children, current)
        if children is None or idx >= len(children):
            return current
        current = children[idx]
    return current


def _fire_cgevent_click(x: int, y: int) -> None:
    """Fire a left-mouse-down + left-mouse-up at (x, y) via CGEventPost.

    Phase 2 will replace this with the C1-C5 channel registry; Phase 1's demo
    uses the bare API to exercise the verifier without a translator layer.
    """
    try:
        from Quartz import (  # type: ignore[import-not-found]
            CGEventCreateMouseEvent,
            CGEventPost,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGHIDEventTap,
            kCGMouseButtonLeft,
        )
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(f"Quartz unavailable: {e}")

    point = (float(x), float(y))
    down = CGEventCreateMouseEvent(
        None, kCGEventLeftMouseDown, point, kCGMouseButtonLeft
    )
    CGEventPost(kCGHIDEventTap, down)
    up = CGEventCreateMouseEvent(
        None, kCGEventLeftMouseUp, point, kCGMouseButtonLeft
    )
    CGEventPost(kCGHIDEventTap, up)


async def run_demo() -> dict:
    """Run the Phase 1 Calculator click demo end-to-end.

    Returns a result dict with this exact shape::

        {
            "session_id": str,
            "composite_key": str,
            "confidence": float,
            "elapsed_ms": float,
            "tier_signals": dict[str, Optional[float]],
            "profile": dict,                 # AppProfile.model_dump(mode="json")
            "post": dict,                    # HoarePost.model_dump(mode="json")
            "action_log_path": str,
            "appprofile_cache_path": str,
            "verified": bool,                # post.verified
        }

    Does NOT print, does NOT call sys.exit. ``main()`` is the CLI wrapper.
    Pytest tests in ``tests/integration/test_calculator_click.py`` and
    ``tests/integration/test_phase1_e2e.py`` import this directly.
    """
    log = structlog.get_logger().bind(demo="calculator_click")

    # Step 1: launch Calculator + classify.
    pid = await asyncio.to_thread(_launch_calculator)
    await asyncio.sleep(0.5)  # let Calculator settle

    profile = await classify(_CALCULATOR_BUNDLE, pid)
    if not profile.ax_rich:
        raise AssertionError(
            f"AppProfile.ax_rich is False — Calculator should be AX-rich. "
            f"profile={profile.model_dump(mode='json')}"
        )

    # Step 2: Set up the full Phase 1 stack (Plans 03-07).
    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop=loop)
    bridge.start()
    axmgr = AXObserverManager(bridge=bridge)
    axmgr.start()
    ws = NSWorkspaceObserver(loop=loop)
    ws.start()

    session = SessionWriter()
    durable = DurableExecutor()
    durable_ready = False
    try:
        await durable.setup()
        durable_ready = True
    except Exception as e:
        log.warning("durable.setup_failed_continuing", error=str(e))

    async with KqueueProcObserver(loop=loop) as kq:
        try:
            l0 = L0Push(axmgr=axmgr, ws=ws, kq=kq)
            l1 = L1Cheap()
            l2 = L2Medium()
            l3 = L3Stub()
            vote = WeightedVote()
            aggregator = Aggregator(l0=l0, l1=l1, l2=l2, l3=l3, vote=vote)

            # Step 3: resolve "5" button and round-trip the state graph.
            button5_elem, button5_axref = await _find_button5(pid, _CALCULATOR_BUNDLE)
            graph = StateGraph()
            graph.upsert(button5_elem)
            roundtrip = graph.get(button5_elem.composite_key)
            if roundtrip is not button5_elem:
                raise AssertionError(
                    f"State-graph round-trip failed for {button5_elem.composite_key}"
                )

            # Step 4: build pre-condition + L1 baseline; subscribe-before-fire.
            modal = await has_blocking_modal(pid, bundle_id=_CALCULATOR_BUNDLE)
            no_modal = modal is None
            if not no_modal:
                raise AssertionError(
                    "A modal is blocking Calculator — close any system "
                    "dialogs before re-running the demo (Pitfall P25)."
                )

            action_id = "demo-click-001"
            step_idx = 1
            pre = HoarePre(
                target_key=button5_elem.composite_key,
                target_exists=True,
                target_enabled=button5_elem.enabled,
                target_role=button5_elem.role,
                role_compatible=True,
                frontmost_app=_CALCULATOR_BUNDLE,
                no_blocking_modal=no_modal,
                timestamp_ns=time.monotonic_ns(),
            )

            # L1 pre-snapshot (parallel with the AX subscribe, just before fire)
            l1_before = await l1.snapshot(button5_elem)

            # SUBSCRIBE-BEFORE-FIRE — Pitfall P28 mitigation, the secret weapon.
            # We register the AXObserver via bridge.subscribe() BEFORE firing
            # so the per-pid CFRunLoop source is hot when the click lands. The
            # aggregator's L0Push.collect will register its own waiter via
            # axmgr.expect() — that waiter filters by action_id, sharing this
            # AXObserver with no double-registration cost (per-pid observer is
            # cached in AXEventBridge._observers).
            notifs = ["AXValueChanged", "AXFocusedUIElementChanged"]
            _pre_sub = bridge.subscribe(
                pid=pid,
                element=button5_axref,
                element_key=button5_elem.composite_key,
                notifications=notifs,
                action_id=action_id,
            )
            log.info(
                "demo.pre_subscribe_anchored",
                subscription_ts_ns=_pre_sub.subscription_ts_ns,
                action_id=action_id,
            )

            # Step 5: FIRE + verify.
            t_start = time.monotonic()
            cx, cy = button5_elem.bbox.centroid
            await asyncio.to_thread(_fire_cgevent_click, int(cx), int(cy))

            action = ActionCanonical(
                id=action_id,
                step_idx=step_idx,
                kind="MUTATE",
                target_key=button5_elem.composite_key,
                action_type="click",
                payload={
                    "x": float(cx),
                    "y": float(cy),
                    "button": "left",
                    "label": button5_elem.label,
                },
                tier=None,
                channel="C3",  # CGEvent
                timestamp_ns=time.monotonic_ns(),
                session_id=session.session_id,
            )

            post = await aggregator.verify(
                action=action,
                target=button5_elem,
                notifs=notifs,
                before_l1=l1_before,
                ax_element=button5_axref,
                timeout_ms=50,
            )
            elapsed_ms = (time.monotonic() - t_start) * 1000.0

            # Step 6: assert the four Phase 1 invariants.
            if not post.verified:
                raise AssertionError(
                    f"verifier failed: confidence={post.confidence}, "
                    f"tier_signals={post.tier_signals}"
                )
            if not (elapsed_ms < 50):
                raise AssertionError(
                    f"latency {elapsed_ms:.2f}ms exceeds 50ms budget — "
                    f"Phase 1 success criterion 1 failed (need elapsed_ms < 50)"
                )
            if post.tier_signals.get("L2") is not None:
                raise AssertionError(
                    "L2 was invoked — Phase 1 invariant violated "
                    "(success criterion 4: '<50ms with no AX subtree walk')"
                )
            if post.tier_signals.get("L3") is not None:
                raise AssertionError(
                    "L3 was invoked — Phase 1 invariant violated "
                    "(L3 LLM stub should never fire when L0+L1 covers the click)"
                )

            # Step 7: persist (best-effort).
            session.append_action_log(
                {
                    "step_idx": step_idx,
                    "action_id": action_id,
                    "tool": "click",
                    "pre": pre.model_dump(mode="json"),
                    "action": action.model_dump(mode="json"),
                    "post": post.model_dump(mode="json"),
                    "elapsed_ms": elapsed_ms,
                }
            )

            if durable_ready:
                try:
                    await durable.checkpoint(
                        session_id=session.session_id,
                        step_idx=step_idx,
                        pre=pre,
                        action=action,
                        post=post,
                    )
                except Exception as e:
                    log.warning("durable.checkpoint_failed", error=str(e))

            # Step 8: build result dict.
            appprofile_cache = (
                Path.home() / ".cua" / "profiles" / f"{_CALCULATOR_BUNDLE}.json"
            )
            return {
                "session_id": session.session_id,
                "composite_key": button5_elem.composite_key,
                "confidence": float(post.confidence),
                "elapsed_ms": float(elapsed_ms),
                "tier_signals": dict(post.tier_signals),
                "profile": profile.model_dump(mode="json"),
                "post": post.model_dump(mode="json"),
                "action_log_path": str(session.action_log_path),
                "appprofile_cache_path": str(appprofile_cache),
                "verified": bool(post.verified),
            }
        finally:
            # Tear down within the kqueue async context manager so its fd is
            # closed AFTER our observers have stopped.
            await axmgr.stop()
            bridge.stop()
            ws.stop()
            if durable_ready:
                try:
                    await durable.aclose()
                except Exception:
                    pass


async def main() -> int:
    """CLI entry point. Pretty-prints the demo result.

    Returns 0 on success, 1 on AssertionError caught from ``run_demo``.
    """
    configure_logging()
    console = Console()
    console.rule("[bold cyan]Phase 1 Calculator demo[/bold cyan]")

    try:
        result = await run_demo()
    except AssertionError as e:
        console.print(f"[bold red]ASSERTION FAILED[/bold red]: {e}")
        return 1
    except Exception as e:
        console.print(f"[bold red]ERROR[/bold red]: {type(e).__name__}: {e}")
        return 1

    profile = result["profile"]
    tier_signals = result["tier_signals"]

    console.print(
        f"AppProfile: ax_rich={profile.get('ax_rich')}, "
        f"ax_observer_works={profile.get('ax_observer_works')}, "
        f"latency_ms={profile.get('probe_latency_ms')}"
    )
    console.print(
        f"State graph round-trip OK: composite_key={result['composite_key']}"
    )
    console.rule("[bold green]VERIFIED[/bold green]")
    console.print(f"session_id    = {result['session_id']}")
    console.print(f"composite_key = {result['composite_key']}")
    console.print(f"confidence    = {result['confidence']:.3f}")
    console.print(f"latency_ms    = {result['elapsed_ms']:.2f}")
    console.print(f"L0 signal     = {tier_signals.get('L0')}")
    console.print(f"L1 signal     = {tier_signals.get('L1')}")
    console.print(
        f"L2 signal     = {tier_signals.get('L2')}  (None expected for Phase 1)"
    )
    console.print(
        f"L3 signal     = {tier_signals.get('L3')}  (None expected for Phase 1)"
    )
    console.print(f"action_log    = {result['action_log_path']}")
    console.print(f"profile_cache = {result['appprofile_cache_path']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
