---
phase: 01-foundation-state-verifier
reviewed: 2026-04-29T22:30:00Z
depth: standard
files_reviewed: 47
files_reviewed_list:
  - cua_overlay/__init__.py
  - cua_overlay/ax/__init__.py
  - cua_overlay/ax/element.py
  - cua_overlay/ax/errors.py
  - cua_overlay/ax/modal_probe.py
  - cua_overlay/ax/observer.py
  - cua_overlay/ax/rate_limit.py
  - cua_overlay/ax/walker.py
  - cua_overlay/demo/__init__.py
  - cua_overlay/demo/calculator_click.py
  - cua_overlay/log.py
  - cua_overlay/mcp_server/__init__.py
  - cua_overlay/mcp_server/__main__.py
  - cua_overlay/mcp_server/healing_tools.py
  - cua_overlay/mcp_server/main.py
  - cua_overlay/mcp_server/proxy.py
  - cua_overlay/persist/__init__.py
  - cua_overlay/persist/durable_step.py
  - cua_overlay/persist/resume.py
  - cua_overlay/persist/session_writer.py
  - cua_overlay/persist/snapshot_io.py
  - cua_overlay/profile/__init__.py
  - cua_overlay/profile/cache.py
  - cua_overlay/profile/capability_probe.py
  - cua_overlay/profile/classifier.py
  - cua_overlay/profile/tcc.py
  - cua_overlay/state/__init__.py
  - cua_overlay/state/causal_dag.py
  - cua_overlay/state/fingerprint.py
  - cua_overlay/state/graph.py
  - cua_overlay/state/ring_buffer.py
  - cua_overlay/state/snapshot.py
  - cua_overlay/verifier/__init__.py
  - cua_overlay/verifier/aggregator.py
  - cua_overlay/verifier/axobserver.py
  - cua_overlay/verifier/distnotif.py
  - cua_overlay/verifier/ensemble/__init__.py
  - cua_overlay/verifier/ensemble/l0_push.py
  - cua_overlay/verifier/ensemble/l1_cheap.py
  - cua_overlay/verifier/ensemble/l2_medium.py
  - cua_overlay/verifier/ensemble/l3_llm.py
  - cua_overlay/verifier/ensemble/weighted_vote.py
  - cua_overlay/verifier/kqueue_proc.py
  - cua_overlay/verifier/nsworkspace.py
  - scripts/doctor.py
  - scripts/init_postgres.py
findings:
  critical: 0
  warning: 6
  info: 14
  total: 20
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-04-29T22:30:00Z
**Depth:** standard
**Files Reviewed:** 47
**Status:** issues_found

## Summary

Phase 1 lands the foundation, state, and verifier subsystems with strong attention to the documented pitfall taxonomy. The hard rules (no recursive AX walks, ≤20/sec/pid rate limiting, subscribe-before-fire, deterministic-first ladder) are all enforced in the source. Pydantic v2 idioms (`model_config = ConfigDict`, `model_validator`, `field_validator`) are used consistently. Threat model mitigations are visible: T-1-01 (stdio-only MCP), T-1-02 (peer auth, no creds in default conn string), T-1-03 (structlog redactor + integer-only pasteboard signal), T-1-06 (kqueue context manager).

No Critical (security or correctness-breaking) issues were found. Six Warnings cover real but contained correctness gaps — the most material being the **shared per-pid AX callback closure** in `ax/observer.py` (subscribing to two elements on the same pid causes `AXEvent.element_key` to be stale), the **healing tool bypassing the verifier wrap**, the **unbounded refcon/callback maps**, and the **callback exception leak risk** when the loop is closing. Fourteen Info items are mostly redundant exception handling, deprecation-prone calls, hardcoded magic constants, and minor duplication.

The `WeightedVote.aggregate()` present-signal renormalization (BLOCKER-1 fix from planning iter 1) is correct — single-signal hits resolve to weight=1.0 in their own column. The 5ms stale-event guard (Pitfall P28) and the `subscribe-before-fire` ordering in `AXObserverManager.expect()` are both implemented as specified. The Calculator demo wires `_fire_after_subscribe` correctly with a 5ms head-start so the dispatcher waiter is registered before the click actually fires.

## Warnings

### WR-01: Shared per-pid AX callback closure leaks stale `element_key` and `pid` to subsequent subscribers

**File:** `cua_overlay/ax/observer.py:255-307`
**Issue:** `subscribe()` creates a fresh `_callback` closure on every call (line 256) that captures the current `pid` and `element_key`, but only registers it with `AXObserverCreate` the FIRST time we see a pid (line 281, gated on `if pid not in self._observers`). For all subsequent subscribes on the same pid (different elements), the new closure is silently discarded — the OLD callback (bound to the FIRST element's `element_key`) fires for every notification on that pid. The retention list `self._callbacks.append(_callback)` is also INSIDE the same `if pid not in self._observers` block, so later closures are not even retained for GC purposes.

Functional impact: `_passes_filter` only matches on `action_id`, `notif`, `pid`, and timestamp — never on `element_key` — so the verifier still works. But every `AXEvent.element_key` after the first subscribe is wrong (it's always the first subscriber's key), which is dead/misleading data for any consumer that logs or routes on it. The Phase 1 demo only subscribes to one element so the bug is invisible; Phase 2's translator + race orchestrator will hit this.

**Fix:**
```python
# Inside subscribe(), before AXObserverAddNotification:
# The callback closure must NOT capture element_key/pid by closure — it must
# resolve them dynamically per-event. Easiest fix: have the callback recover
# everything from the refcon and a shared subscription table.

# Replace the closure with one that resolves element_key from refcon_map:
@objc.callbackFor(AXObserverCreate)
def _callback(observer, axelem, notif_name, refcon):
    resolved_action_id: Optional[str] = None
    resolved_element_key: str = ""
    resolved_pid: int = 0
    try:
        if refcon is not None:
            resolved_action_id = refcon_map.get(int(refcon))
            # Look up the latest sub for this action_id
            for s in self._subscriptions:
                if s.action_id == resolved_action_id:
                    resolved_element_key = s.element_key
                    resolved_pid = s.pid
                    break
    except Exception:
        pass
    event = AXEvent(
        pid=resolved_pid,
        element_key=resolved_element_key,
        notif=str(notif_name),
        user_info=None,
        event_ts_ns=time.monotonic_ns(),
        action_id=resolved_action_id,
    )
    loop.call_soon_threadsafe(queue.put_nowait, event)
```

### WR-02: `click_with_healing` bypasses the verifier wrap that was registered for upstream `click`

**File:** `cua_overlay/mcp_server/healing_tools.py:94-103`
**Issue:** The healing tool's docstring claims it "runs the L0+L1 verifier ladder" (line 60-61) but the implementation calls `upstream.call_tool("click", ...)` directly, bypassing the `register_proxied_tool` wrap that `main.py` already installed for the upstream `click` tool. The wrap in `proxy.py:160-252` is what runs the verifier ladder, captures the L1 baseline, and writes the action log + Postgres checkpoint. By going to upstream directly, none of that fires — the host gets an unwrapped click result with a `phase=1` note glued on top.

Two consequences: (a) docstring lies to MCP hosts that introspect tool descriptions; (b) action log + Postgres checkpoint never write for healing-named calls, so the audit trail is incomplete.

**Fix:**
```python
# Option A (recommended): delegate to the proxy's own wrapped click tool so the
# verifier ladder + action log + checkpoint all run.
async def click_with_healing(x, y, bundle_id="", pid=0, label=""):
    # Use proxy.call_tool not upstream.call_tool so the registered _wrapped
    # function fires (PRE-snapshot + verify + LOG + CHECKPOINT).
    result = await proxy.call_tool("click", arguments={
        "x": x, "y": y, "bundle_id": bundle_id, "pid": pid, "label": label,
    })
    return {"result": result, "session_id": deps.session.session_id, ...}

# Option B: drop the misleading docstring claim and document that Phase 1
# healing is a thin label-only wrapper. Implementation matches docstring.
```

### WR-03: Unbounded growth of `_callbacks`, `_refcon_to_action`, and `_subscriptions` lists

**File:** `cua_overlay/ax/observer.py:108-112,247-248,307`
**Issue:** Long-running sessions accumulate entries in three structures that are never pruned:
- `self._callbacks` — every successful first-subscribe-per-pid retains the closure forever (line 280).
- `self._refcon_to_action` — every action_id maps in (line 248); never removed.
- `self._subscriptions` — appended on every subscribe (line 307); never removed.

Phase 1 sessions are short and the demo fires one action, so the leak is invisible. Phase 3's race orchestrator will cycle hundreds of actions per minute and the maps will grow without bound. Each entry is small (~100 bytes) so this is a slow leak, not a fast one — but it also means the refcon collision risk (see WR-04) grows monotonically.

**Fix:**
```python
# Add a cleanup hook on Subscription tear-down (or fold it into AXObserverManager.expect()
# timeout/completion path). Each Subscription should remove its refcon mapping
# and itself from _subscriptions on completion.
def _release_subscription(self, sub: Subscription) -> None:
    # Find the refcon that mapped to this sub.action_id and drop it.
    to_drop = [k for k, v in self._refcon_to_action.items() if v == sub.action_id]
    for k in to_drop:
        self._refcon_to_action.pop(k, None)
    self._subscriptions = [s for s in self._subscriptions if s.action_id != sub.action_id]
    # Note: AXObserverRemoveNotification is the proper way to release the
    # AX-level subscription; do that here too.
```

### WR-04: AX callback can raise `RuntimeError` when asyncio loop is closed during stop()

**File:** `cua_overlay/ax/observer.py:256-274`
**Issue:** The CFRunLoop callback unconditionally calls `loop.call_soon_threadsafe(queue.put_nowait, event)` (line 274). If the asyncio loop is closed (because `stop()` was called and the event loop has shut down) while the CFRunLoop thread is still mid-callback, `call_soon_threadsafe` raises `RuntimeError: Event loop is closed`. The exception escapes back into the C boundary, which on PyObjC is undefined behavior — best case a logged traceback, worst case a SIGABRT in the AX framework's CFRunLoop dispatch.

The race window is small (we set `_stop_requested` then call `CFRunLoopStop`) but real on stress shutdown paths. The 1-second `CFRunLoopRunInMode` poll means the thread can be servicing a callback up to 1s after stop() is called.

**Fix:**
```python
def _callback(observer, axelem, notif_name, refcon):
    try:
        resolved_action_id: Optional[str] = None
        if refcon is not None:
            try:
                resolved_action_id = refcon_map.get(int(refcon))
            except Exception:
                pass
        event = AXEvent(
            pid=pid,
            element_key=element_key,
            notif=str(notif_name),
            user_info=None,
            event_ts_ns=time.monotonic_ns(),
            action_id=resolved_action_id,
        )
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            # Loop has been closed (stop() raced with this callback). Drop
            # the event silently — no waiter can receive it anyway.
            pass
    except Exception:
        # Defensive: never let an exception escape into the C boundary.
        pass
```

### WR-05: `_mask_conn` over-redacts conn strings without a password

**File:** `cua_overlay/persist/durable_step.py:161-169`
**Issue:** The mask logic is `if "@" in self._conn_string and ":" in self._conn_string.split("@")[0]`. For a conn string like `postgresql://user@host:5432/db` (peer auth — user but no password), `split("@")[0]` returns `postgresql://user`, which contains `:` (from the `postgresql:` URL scheme). So the function falsely redacts to `postgresql://***@***` even though there's no password to leak.

Functional impact: harmless over-redaction, but operators looking at logs to debug a "wrong host?" scenario will see only `***`. T-1-02 mitigation works (no false negative — passwords are still hidden), but the false positive obscures useful data.

**Fix:**
```python
def _mask_conn(self) -> str:
    """Return a structlog-safe representation of the conn string."""
    # Pattern: postgresql://user:password@host  → mask
    # Pattern: postgresql://user@host           → don't mask (peer auth)
    # Pattern: postgresql://host                → don't mask
    if "@" not in self._conn_string:
        return self._conn_string
    # Strip scheme://, then check if "user:password" form is present.
    after_scheme = self._conn_string.split("://", 1)[-1]
    userinfo = after_scheme.split("@", 1)[0]
    if ":" in userinfo:
        return "postgresql://***@***"
    return self._conn_string
```

### WR-06: `KqueueProcObserver` uses deprecated `asyncio.get_event_loop()` fallback

**File:** `cua_overlay/verifier/kqueue_proc.py:47`
**Issue:** `self.loop = loop or asyncio.get_event_loop()` calls `asyncio.get_event_loop()` when no loop is passed. In Python 3.12, this emits a `DeprecationWarning` if no loop is running and may raise in future versions. The constructor is called from `mcp_server/main.py:109` and `demo/calculator_click.py:457` with an explicit `loop=loop` argument, so the fallback rarely fires today — but tests instantiating `KqueueProcObserver()` with no args (and outside an async context) will warn / break.

**Fix:**
```python
def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    self.loop = loop or asyncio.get_running_loop()
    # If get_running_loop fails (called outside async context), force callers
    # to pass loop= explicitly. That's a stricter contract than the deprecated
    # get_event_loop fallback.
```

## Info

### IN-01: AXObserver refcon collisions possible from `hash(action_id)` truncation

**File:** `cua_overlay/ax/observer.py:247-248`
**Issue:** `action_refcon = abs(hash(action_id)) & 0xFFFFFFFF` truncates Python's 64-bit string hash to 32 bits. With UUID4-shaped action_ids, the collision rate is ~1 in 2^32 ≈ 4 billion. Practical risk is extremely low for Phase 1 — a single session running for ~1000 hours at 100 actions/sec hits ~1 collision. Worth fixing before that scale lands. When a collision happens, `refcon_map[action_refcon] = action_id` overwrites the older mapping silently.
**Fix:** Use a monotonically increasing counter as the refcon, paired with a dict `{counter: action_id}`. Trivially collision-free, no hash math needed. Also fixes WR-03 cleanup since the counter range stays compact.

### IN-02: Hardcoded magic number `-25209` for `kAXErrorNotificationAlreadyRegistered`

**File:** `cua_overlay/ax/observer.py:300`
**Issue:** `if err != 0 and err != -25209: ...` uses a magic literal instead of the named constant `kAXErrorNotificationAlreadyRegistered` from HIServices. The same module imports `axerror_from_code` and other `kAXError*` constants from the live framework. Hardcoding -25209 risks silent breakage if Apple ever renumbers (extremely unlikely but documented avoidance pattern in `errors.py`).
**Fix:** Import `kAXErrorNotificationAlreadyRegistered` from HIServices alongside the other constants and reference it: `if err != 0 and err != int(kAXErrorNotificationAlreadyRegistered): ...`

### IN-03: Redundant `(asyncio.TimeoutError, Exception)` catches

**File:** `cua_overlay/profile/capability_probe.py:98,149`, `cua_overlay/profile/classifier.py:97`
**Issue:** Catching `(asyncio.TimeoutError, Exception)` is redundant — `Exception` is a base class for `asyncio.TimeoutError` (it's `BaseException` → `Exception` → `TimeoutError` → `asyncio.TimeoutError` in 3.11+). The tuple has no effect beyond `Exception` alone.
**Fix:** Replace with `except Exception:`. If you specifically want to log timeouts differently from other failures, split the catch.

### IN-04: Redundant `(ImportError, Exception)` catch in `NSWorkspaceObserver.stop`

**File:** `cua_overlay/verifier/nsworkspace.py:97`
**Issue:** Same as IN-03 — `Exception` catches `ImportError`.
**Fix:** `except Exception:` alone (with the existing `# pragma: no cover` comment).

### IN-05: `_step_counter` global dict in MCP proxy

**File:** `cua_overlay/mcp_server/proxy.py:67`
**Issue:** Module-level `_step_counter = {"value": 0}` is mutated from inside `_wrapped` on every action-class tool call. CPython's GIL makes `_step_counter["value"] += 1` atomic so there's no torn read, but the pattern is fragile: if `proxy.py` is ever imported in two MCP server processes (unlikely but possible during testing), each gets its own counter starting at zero. A counter scoped to the `ProxyDeps` or `SessionWriter` would be clearer.
**Fix:** Move into `SessionWriter` as `next_step_idx() -> int` so step counting is per-session by construction.

### IN-06: `_build_minimal_target` produces composite_keys that collide for repeated clicks at same coords

**File:** `cua_overlay/mcp_server/proxy.py:73-104`
**Issue:** The fallback `UIElement` has no `ax_identifier`, no `role_path` (other than `AXButton[?]`), and a fabricated 20×20 bbox centred on (x, y). The composite_key falls through to `path:bundle_id:AXApplication/AXButton[?]:label` (Tier 2) or `bbox:bundle_id:AXButton:cx:cy` (Tier 3). Two distinct clicks at the same coords with the same label would have the same composite_key. Phase 2's translator layer is supposed to fix this by populating real AX subtree info — but the docstring should call out the collision risk explicitly so callers don't depend on uniqueness.
**Fix:** Add `# Phase 1 caveat: composite_key not unique across repeated clicks at same coords. Phase 2 translator fills real ax_identifier.` to the docstring.

### IN-07: `payload=dict(kwargs)` in `ActionCanonical` could leak future caller secrets

**File:** `cua_overlay/mcp_server/proxy.py:194`
**Issue:** The action canonical record stores `payload=dict(kwargs)` and is later written verbatim to `action_log.ndjson` via `deps.session.append_action_log(...)`. The structlog redactor only fires for events emitted via `structlog.get_logger()` — `append_action_log` is a raw NDJSON sink (documented in `session_writer.py:111`). No current upstream tool ships a sensitive kwarg, but a future `type_text(text=...)` could pass clipboard contents and they'd land in the action log.
**Fix:** Run `payload` through a redactor before writing it. Or add `_SENSITIVE_FIELDS` checking inside `append_action_log` itself. The current contract puts the burden on every call site to remember — easy to forget.

### IN-08: `_coords_to_bbox` duplicated between `walker.py` and `calculator_click.py`

**File:** `cua_overlay/ax/walker.py:205-219`, `cua_overlay/demo/calculator_click.py:280-315`
**Issue:** The demo defines its own `_coords_to_bbox` because it needs the `AXValueGetValue` extraction path for real AX runtime tuples. Walker's version handles the test-mock-tuples path. Functional behavior matches in both branches, but maintaining two copies invites drift.
**Fix:** Promote the demo's combined version (try AXValueGetValue first, fall back to plain tuple) into `walker.py` and import it from the demo. Move the helper to `cua_overlay.ax.coords` if a shared module makes more sense.

### IN-09: Walker `max_depth=3` semantics are off-by-one vs docstring

**File:** `cua_overlay/ax/walker.py:1-7,130`
**Issue:** Docstring says "max_depth=3 — children of children of children, no deeper" implying 3 levels including root. The check is `if depth + 1 <= max_depth:` — at depth=2, this allows children to be enqueued at depth=3, where they're popped, processed, and the depth-cap fires (no further children). So the walker actually visits root + 3 child levels = 4 total levels. Either the cap should be 2 (to match the prose) or the prose should say "root + 3 levels of children = 4 layers".
**Fix:** Adjust docstring (cheap) or default (semantically louder). Recommend updating `__init__.py` and `walker.py` docstrings to "root + max_depth levels of children" so the math is unambiguous.

### IN-10: `SessionWriter.__init__` `touch()` updates mtime on existing logs

**File:** `cua_overlay/persist/session_writer.py:73-75`
**Issue:** When a `SessionWriter` is constructed with an existing `session_id` (e.g. resume after crash), `touch()` updates the mtime of `heals.ndjson` and `action_log.ndjson` even though their content is preserved. Forensic timeline analysis becomes confusing — the file's mtime no longer reflects the last actual write.
**Fix:** Skip `touch()` if the file already exists: `if not (self._dir / fname).exists(): (self._dir / fname).touch()`.

### IN-11: `fingerprint.py` Tier 3 fallback can collide for stacked windows

**File:** `cua_overlay/state/fingerprint.py:38-39`
**Issue:** Tier 3 uses `bbox:bundle_id:role:cx:cy`. Two distinct elements with the same role at the same centroid (e.g. two stacked windows with overlapping menu items) collide. Phase 1 single-window scope makes this invisible. Worth flagging in the docstring.
**Fix:** Document the limitation in `compute_composite_key`'s docstring; consider including `window_id` in the Tier 3 key in a future plan.

### IN-12: `state/graph.py` is not thread-safe

**File:** `cua_overlay/state/graph.py:139-173`
**Issue:** `StateGraph.upsert`/`get`/`add_child` mutate `self.nodes` and `self.edges` without any lock. CPython's GIL makes individual dict assignments atomic, but compound operations (e.g. `add_child` does upsert+upsert+append) can interleave with concurrent mutations. Phase 1 single-task usage hides this; Phase 3's race orchestrator with multiple translator branches mutating the graph in parallel will hit it.
**Fix:** Document Phase 1 single-task contract in the docstring; in Phase 3, wrap with `asyncio.Lock` or move to a copy-on-write structure.

### IN-13: `axerror_from_code(code, message)` parameter ordering inverts standard

**File:** `cua_overlay/ax/errors.py:123-130`
**Issue:** Standard exception constructors take message first; `axerror_from_code(code, message)` has them reversed. Most call sites use the keyword-second form, but the positional `axerror_from_code(err, "AX read failed: ...")` is easy to mis-type. Minor ergonomics.
**Fix:** Either rename to `axerror_from_code(message, code)` to match `Exception(message, *args)` ordering, or switch every call site to keyword `axerror_from_code(code=err, message=...)` for clarity.

### IN-14: `walker.py` imports unused `kAXErrorAttributeUnsupported`/`kAXErrorActionUnsupported` indirectly

**File:** `cua_overlay/ax/walker.py:31`
**Issue:** Walker imports only `kAXErrorAPIDisabled` and `kAXErrorCannotComplete` from `errors.py`, which is correct. But the wider AX module re-exports six error constants. Consumers downstream should be aware that walker's `_read_attr` swallows `kAXErrorAttributeUnsupported` (it returns `None`) and only raises on the two it lists. Worth adding a comment so readers don't expect the typed-error contract from `AXUIElementWrapper.read_attribute`.
**Fix:** Add a one-line comment in `walker._read_attr`: `# NOTE: only raises on cannot_complete + api_disabled. Other AX errors return None.`

---

_Reviewed: 2026-04-29T22:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
