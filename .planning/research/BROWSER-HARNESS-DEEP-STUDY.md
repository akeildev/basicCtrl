# Browser-Harness Deep-Study: Self-Healing Patterns for CUA-Maximalist

## Executive Summary

Browser-harness is a ultra-thin (~592 lines Python) self-healing browser control framework that connects directly to Chrome's Developer Protocol (CDP) over WebSocket and exposes a minimal surface (`helpers.py` ~195 lines) for agents to extend. It solves the core self-healing problem for browser automation: **coordinate clicks over TCP/IP compositor are bulletproof, deterministic verification (screenshot + state checks) is cheaper than LLM recovery, and the framework must stay small enough that agents edit it mid-task to add missing capabilities.** No retry loops, no supervision layer, no manager abstraction—just a Unix socket relay daemon, raw CDP, and an event buffer. It is the single best implementation of browser automation self-healing that exists, and cua-maximalist should adopt its entire architecture for native-app paths (AX, AppleScript, Vision, Pixel).

---

## Architecture: Layering & Lifecycle

```
User's running Chrome
       ↓ (CDP WS: /json/version)
daemon.py (asyncio CDPClient → Unix socket)
  - Daemon.__init__(): hold CDPClient + session_id + event buffer
  - Daemon.attach_first_page(): find a real page, skip omnibox popups
  - Daemon.handle(req): route CDP or control meta → reply
  - serve(): Unix socket listener (one-request-per-connection)
       ↓ (/tmp/bu-<NAME>.sock)
helpers.py + run.py + user Python
  - _send(req): socket roundtrip JSON
  - cdp(method, **params): raw CDP passthrough
  - click(x, y), type_text(), press_key(): input dispatch
  - screenshot(), page_info(), js(): verification
  - new_tab(), switch_tab(), ensure_real_tab(): tab control
  - wait_for_load(), wait(): delays
```

**Key lifecycle facts:**

1. **run.py (36 lines):** Entry point. Calls `ensure_daemon()` (auto-start daemon on first run), then `exec(stdin)` with helpers pre-imported.

2. **admin.py (299 lines):** Daemon lifecycle. `ensure_daemon(name, env)` is **idempotent**—it checks `daemon_alive()` via socket connect, spawns subprocess if needed, polls until socket appears. `restart_daemon(name)` is best-effort shutdown: sends `{"meta":"shutdown"}` over socket, SIGTERMs if needed, unlinks files.

3. **daemon.py (249 lines):** Long-lived asyncio server. `Daemon.attach_first_page()` (line 111–132) attaches to the first **real** page, filtering out `chrome://omnibox-popup...` and `chrome://inspect`. Event tap on line 146–155 intercepts CDP events into a bounded deque (500-entry buffer), surfaces dialogs in `page_info()`. Re-attaches on stale session (line 184–186).

4. **Namespacing via BU_NAME:** Each `BU_NAME` gets its own socket `/tmp/bu-{NAME}.sock`, log `/tmp/bu-{NAME}.log`, pid `/tmp/bu-{NAME}.pid`. Enables **parallel agents**—each with distinct browser session (via `start_remote_daemon("name")` + `BU_NAME=name browser-harness ...`).

---

## 10 Core Self-Healing Patterns

### 1. **Coordinate Clicks Default (No DOM Clicks)**
**File:** `helpers.py:70–72`, `SKILL.md:141–142`, `SKILL.md:129`

```python
def click(x, y, button="left", clicks=1):
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)
```

**Why:** `Input.dispatchMouseEvent` at the **compositor level** passes through iframes, shadow DOM, and cross-origin frames without DOM read/write. Browser automation docs (SKILL.md "Gotchas") explicitly state: "Prefer compositor-level actions over framework hacks." Zero JS injection = no antibot detection, no async race conditions.

**CUA Lesson:** Replace AX click + AppleScript click hybrid with **guaranteed-deliverable coordinate action** at C1 (SLEventPostToPid) or C2 (AX kAXPress) level, but verify with deterministic observer (AXObserver push events) not LLM second-guessing.

---

### 2. **Screenshot First, Then Act, Then Verify**
**File:** `SKILL.md:128–129`, `SKILL.md:183–185`

Pattern in domain skills (e.g., `amazon/product-search.md:44–50`, `hackernews/scraping.md:15–27`):

```python
# Discovery/exploration
screenshot()  # to find visible targets

# Action
click(x, y)   # act on visible coordinates

# Verification
screenshot()  # verify state changed
```

**Why:** Screenshots are often **faster** than DOM reads (one CDP call, base64 decode, disk write vs. recursive JS tree walk). The image tells you visible errors, modal overlays, loading spinners, and whether navigation happened—LLM-free. Bounded by <2s total per action when using coordinate clicks.

**CUA Lesson:** Snapshot AX tree + take screenshot every action. Compare pixel dHash (ImageHash) + AX subtree hash for **deterministic** verification before invoking L3 LLM verifier. This is what Tier 0 (Apple FM 3B) and L1/L2 ensemble do.

---

### 3. **Omnibox Popup Trap & Stale Tab Recovery**
**File:** `daemon.py:99–101`, `daemon.py:111–123`, `helpers.py:146–158`, `SKILL.md:170–172`

```python
def is_real_page(t):
    return t["type"] == "page" and not t.get("url", "").startswith(INTERNAL)

async def attach_first_page(self):
    targets = (await self.cdp.send_raw("Target.getTargets"))["targetInfos"]
    pages = [t for t in targets if is_real_page(t)]
    if not pages:
        # No real pages — create one instead of attaching to omnibox popup
        tid = (await self.cdp.send_raw("Target.createTarget", {"url": "about:blank"}))["targetId"]
        log(f"no real pages found, created about:blank ({tid})")
        pages = [{"targetId": tid, "url": "about:blank", "type": "page"}]
    self.session = (await self.cdp.send_raw(
        "Target.attachToTarget", {"targetId": pages[0]["targetId"], "flatten": True}
    ))["sessionId"]
```

**Why:** When Chrome first opens, `Target.getTargets` includes a fake `chrome://omnibox-popup...` target with 1px viewport. If daemon attaches there, all work happens invisibly. Solution: **explicitly create about:blank** when no real pages exist. On reconnect, `ensure_real_tab()` calls `list_tabs(include_chrome=False)` and re-attaches to the first non-internal tab.

**Stale session recovery (line 184–186):**
```python
except Exception as e:
    msg = str(e)
    if "Session with given id not found" in msg and sid == self.session and sid:
        log(f"stale session {sid}, re-attaching")
        if await self.attach_first_page():
            return {"result": await self.cdp.send_raw(method, params, session_id=self.session)}
    return {"error": msg}
```

**CUA Lesson:** For AX, detect "app frozen" or "AX tree stale" and auto-recovery-loop to the root accessibility object. For AppleScript, catch "scripting component not found" and re-invoke via fresh `NSAppleScript`. For Vision, on timeout retry with fallback model (e.g., ShowUI-2B if UI-TARS-1.5 coord bug hits).

---

### 4. **Event Buffering & Dialog Detection**
**File:** `daemon.py:107`, `daemon.py:146–155`, `helpers.py:55–67`, `interaction-skills/dialogs.md`

```python
self.events = deque(maxlen=BUF)  # BUF=500
self.dialog = None

async def tap(method, params, session_id=None):
    self.events.append({"method": method, "params": params, "session_id": session_id})
    if method == "Page.javascriptDialogOpening":
        self.dialog = params
    elif method == "Page.javascriptDialogClosed":
        self.dialog = None
```

And in helpers:
```python
def page_info():
    dialog = _send({"meta": "pending_dialog"}).get("dialog")
    if dialog:
        return {"dialog": dialog}  # Caller must handle before continuing
    # ... otherwise return viewport info
```

**Why:** Events (navigation, load, dialog) arrive asynchronously. Buffering them into a ring-deque lets agents `drain_events()` and inspect what happened without polling. Dialog detection in `page_info()` surfaces frozen pages immediately (JS thread blocked by `alert()`/`confirm()`/`beforeunload`).

**CUA Lesson:** AXObserver push events (kAXValueChanged, kAXMenuOpened, etc.) are the AX equivalent. Subscribe **before** action fires, then check the event stream post-action. For Pixel actions, use network request capture (Page.Network events) to detect navigation without waiting for DOM.

---

### 5. **Session Routing: Target-level vs. Session-level CDP**
**File:** `daemon.py:176–179`, `admin.py:132**

```python
# Browser-level Target.* calls must not use a session (stale or otherwise).
# For everything else, explicit session in req wins; else default.
sid = None if method.startswith("Target.") else (req.get("session_id") or self.session)
```

**Why:** `Target.getTargets`, `Target.createTarget`, `Target.attachToTarget` are **browser-level**—they don't use a session ID. Other calls (Page, Runtime, DOM, Input, Network) are **session-scoped**. The daemon auto-routes: if you call `list_tabs()` (which calls `cdp("Target.getTargets")`), it sends `{"method": "Target.getTargets", "params": {}, "session_id": null}`. If you call `page_info()`, it routes to `self.session` (the attached tab's session).

**CUA Lesson:** For CDP-Electron apps (T2), maintain a session per app instance. For AX (T1), the "session" is the PID + AX tree generation counter. For AppleScript (T3), maintain a script context per target app. Route browser-level commands (enumerate all apps) separately from app-level commands (click button on a specific app).

---

### 6. **Deterministic Wait: Poll for document.readyState, Not Event Waves**
**File:** `helpers.py:172–178`, `SKILL.md:131`

```python
def wait_for_load(timeout=15.0):
    """Poll document.readyState == 'complete' or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js("document.readyState") == "complete": return True
        time.sleep(0.3)
    return False
```

**Why:** `document.readyState == 'complete'` is **deterministic**. Polling every 300ms is wasteful but bulletproof. (A better approach: subscribe to `Page.loadEventFired`, but this works.) Amazon skill (line 18–19) explicitly calls `wait_for_load()` then `wait(2)` because "dynamic content needs ~2s after readyState=complete"—proving the LLM's heuristic: waits are site-specific, timeout is king.

**Gotcha in SKILL.md:105:** "A **wait** that `wait_for_load()` misses, with the reason" is worth PRing back to domain-skills—these are lessons agents should remember.

**CUA Lesson:** For AX, poll for tree stability (take two snapshots 200ms apart, if they're identical by hash, tree is ready). For Pixel, poll for page visual stability (2+ consecutive dHash matches = ready). Respect **timeout over polls**—never loop forever.

---

### 7. **Profile Sync & Authenticated Sessions**
**File:** `admin.py:175–202`, `admin.py:215–241`, `admin.py:243–299`, `SKILL.md:44–64`, `interaction-skills/profile-sync.md`

```python
def start_remote_daemon(name="remote", profileName=None, **create_kwargs):
    if profileName:
        create_kwargs["profileId"] = _resolve_profile_name(profileName)
    browser = _browser_use("/browsers", "POST", create_kwargs)
    ensure_daemon(
        name=name,
        env={"BU_CDP_WS": _cdp_ws_from_url(browser["cdpUrl"]), "BU_BROWSER_ID": browser["id"]},
    )
    _show_live_url(browser.get("liveUrl"))
    return browser

def sync_local_profile(profile_name, browser=None, cloud_profile_id=None, ...):
    """Shells out to profile-use sync. Requires BU_BROWSER_ID + BROWSER_USE_API_KEY."""
    cmd = ["profile-use", "sync", "--profile", profile_name]
    # ... construct cmd ... run subprocess ... parse UUID from output
```

**Why:** Cookie-based login state is portable across browsers. `profile-use` (external tool) reads Chrome's Cookies DB (requires exclusive file lock, so target browser must be closed) and syncs cookies to a cloud profile UUID. Then `start_remote_daemon(profileName="my-work")` boots a headless browser with those cookies pre-loaded.

**CUA Lesson:** For native apps, there is no cookie sync—each app has its own keychain/state store. But the **pattern** is valuable: capture login state (screenshot + app state), restore in recovery (B1–B5 branches). Use Keychain API (PyObjC Security framework) to persist auth tokens.

---

### 8. **Async I/O with Proper Timeout Handling**
**File:** `daemon.py:134–143`, `daemon.py:126–129`

```python
async def start(self):
    self.stop = asyncio.Event()
    url = get_ws_url()
    self.cdp = CDPClient(url)
    try:
        await self.cdp.start()
    except Exception as e:
        raise RuntimeError(f"CDP WS handshake failed: {e} -- click Allow in Chrome if prompted, then retry")
    
    # Enable domains with timeouts
    for d in ("Page", "DOM", "Runtime", "Network"):
        try:
            await asyncio.wait_for(
                self.cdp.send_raw(f"{d}.enable", session_id=self.session),
                timeout=5
            )
        except Exception as e:
            log(f"enable {d}: {e}")
```

**Why:** Network timeouts are unpredictable. Use `asyncio.wait_for(task, timeout=5)` to convert hung coroutines into `TimeoutError`. The daemon logs failures but continues (don't crash on Network.enable timeout—many calls don't need it).

**CUA Lesson:** All CDP calls should have timeouts. For AX, use `asyncio.wait_for(asyncio.to_thread(ax_read_attr))` to prevent GIL hangs. For Vision, set model inference timeout (mlx_vlm doesn't timeout by default).

---

### 9. **Unix Socket IPC Over TCP (One Request Per Connection)**
**File:** `daemon.py:194–210`, `helpers.py:26–38`

```python
async def handler(reader, writer):
    try:
        line = await reader.readline()
        if not line: return
        resp = await d.handle(json.loads(line))
        writer.write((json.dumps(resp, default=str) + "\n").encode())
        await writer.drain()
    finally:
        writer.close()

server = await asyncio.start_unix_server(handler, path=SOCK)
```

Helpers side:
```python
def _send(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk: break
        data += chunk
    s.close()
    r = json.loads(data)
    if "error" in r: raise RuntimeError(r["error"])
    return r
```

**Why:** **One request per connection.** No persistent TCP connection, no state on the client side, no connection pooling bugs. Just: open socket, send JSON line, read JSON line, close. Trades latency (~1ms per call) for total simplicity—no framing errors, no lingering data, no backpressure handling.

**CUA Lesson:** For cua-maximalist, the Python overlay talks to Swift sidecars over Unix domain sockets the same way. Keep IPC **dumb and stateless**.

---

### 10. **No Manager/Retry/Supervisor Framework**
**File:** `SKILL.md:146`, `README.md:44–50`, `daemon.py:232–249`

```
~592 lines total:
  - install.md — bootstrap only
  - SKILL.md — day-to-day usage doc
  - run.py — 36 lines
  - helpers.py — 195 lines
  - admin.py + daemon.py — 361 lines (daemon + bootstrap)
  - interaction-skills/*.md — recipes, not code
```

**Why:** The framework is **prescriptive about what NOT to add**: "Don't add a manager layer. No retries framework, session manager, daemon supervisor, config system, or logging framework" (SKILL.md:146). Why? Because:

1. **The agent writes what's missing.** If a helper is missing, agents edit `helpers.py` and commit it back (README.md:56–59). No plugin system, no versioning headache.
2. **Retries belong in domain logic.** Amazon skill calls `wait_for_load(); wait(2)` because Amazon needs it—not a generic retry loop.
3. **Logging is simple.** Daemon logs to `/tmp/bu-{NAME}.log`. Helpers raise exceptions. Agent handles them.

**CUA Lesson:** cua-maximalist's Python overlay should be **<2500 LOC**. All the heavy lifting (racing, ensemble, recovery branches B1–B5) lives in LangGraph nodes, not in a supervisor. The overlay routes action → channel, gets result → verifier, handles exception → next branch. That's it. No manager trying to be smart.

---

## The Skill Pattern: Discovery + Contribution Model

### Structure of Domain Skills

**Example: `amazon/product-search.md`** (199 lines, field-tested 2025-04-18)

Sections:
1. **Navigation** (URL patterns, query params, direct vs. search-box)
2. **Session gotcha** (use `new_tab()` on first visit, `goto()` after)
3. **Search results extraction** (selector `[data-component-type="s-search-result"]`, 22 results/page, field notes on each field)
4. **Product detail page** (confirmed selectors for title, price, rating, etc.)
5. **Best sellers page** (migration from `.zg-item-immersion` to CSS modules; use `[data-asin]` + `img[alt]` for title)
6. **Pagination** (next page URL pattern, page number construction)
7. **Result count** (regex pattern in result info bar)
8. **CAPTCHA detection** (defensive checks; logged-in sessions avoid it)
9. **Gotchas** (15 specific traps and solutions; `data-asin` can be empty, price split across DOM nodes, ASIN from URL pattern, etc.)

**Example: `hackernews/scraping.md`** (244 lines)

Opens with a **decision table**:
| Goal | Best approach | Latency |
|------|---|---|
| Front page | `http_get` + regex | 170ms |
| Historical search | Algolia API | 400ms |
| Comment tree | Algolia items API | 300ms |

Then **4 paths**:
1. HTTP GET front page (30 stories in ~34KB HTML, regex extraction)
2. Algolia search API (full metadata, up to 1000 hits, tag/numeric filters)
3. Official HN Firebase API (ranked story IDs, single-item fetches)
4. Comment thread HTML (flat, all comments in one request, no pagination)

**Conclusion: "Never use a browser for HN."** All data is in plain HTML or JSON APIs. `http_get` is 20–50× faster than screenshot + JS parsing.

### Why This Works as a Self-Improving System

1. **Agent-generated, not hand-authored.** README.md:56–59: "Skills are written by the harness, not by you. Just run your task with the agent — when it figures something non-obvious out, it files the skill itself."

2. **Contributors PR back.** README.md:52–59: "Open a PR with the generated `domain-skills/<site>/` folder — small and focused is great." Each agent that solves a new domain adds a new file, and the repo grows.

3. **Durable shape, not diary entries.** SKILL.md:108–118: "The *durable* shape of the site — the map, not the diary. Focus on what the next agent on this site needs to know before it starts: URL patterns, private APIs, stable selectors, site structure, framework quirks, waits, traps."

4. **Stable selectors + traps.** SKILL.md:120–124: "Do not write raw pixel coordinates… Describe how to *locate* the target… never secrets, cookies, session tokens." Amazon skill's 15 gotchas are **procedural facts**—they survive DOM changes because they describe the selector strategy, not specific class names.

5. **Private API shortcuts.** SKILL.md:99–101: "A **private API** the page calls… often 10× faster than DOM scraping." DuckDuckGo skill: use `https://api.duckduckgo.com/?q=...&format=json` instead of Googling. HN skill: use Algolia or Firebase APIs instead of scraping the front page.

### CUA Lesson: Episodic Memory + Recipe Synthesis

cua-maximalist has the same opportunity:

- **T1 (AX), T3 (AppleScript), T4 (Vision), T5 (Pixel)** each produce a **cassette** (JSON Lines: `{step_idx, hoare_pre, action, hoare_post, screenshot_pHash, ax_tree_hash, healed_selectors[]}`).
- **Synthesis engine** (like agents authoring domain skills) analyzes cassettes: "This button always appears at `x,y = 500, 400` relative to window origin. Selector is `.dialog button.primary`. Tier 0 (Apple FM 3B) correctly IDs it 99% of the time when dialog is open."
- **Recipes** (parallel to domain-skills) capture: URL pattern, app state quirks, reliable selectors/coordinates per Tier, fallback chains (if Tier 0 fails, try Tier 1 + AX, etc.), waits (app needs 500ms after menu open before subitem coordinates are valid).
- **Contribution loop:** After healing a tough bug (e.g., F9 verifier finding AX stale-session bug), PR a new recipe to `.planning/recipes/<app>/<action>.md`.

---

## Concrete Recommendations for CUA-Maximalist

### A. Browser-Side Improvements (T2 CDP)

**Current state:** T2 CDP translator exists but verifier + recovery are basic.

**Adopt from browser-harness:**

1. **Use coordinate clicks exclusively (C5 Input.dispatchMouseEvent)** rather than DOM clicks via Runtime.evaluate. File: `/cua-maximalist/overlay/translators/t2_cdp.py` should emit `C5_CDP_INPUT` actions, not `C4_APPLESCRIPT` DOM-based alternatives for web targets.

2. **Screenshot-then-verify loop in T2 verifier** before invoking L3 LLM. Current verifier (likely in `overlay/verifiers/`) should:
   - Post-action: screenshot + dHash via ImageHash
   - Compare to pre-action dHash (if major pixel region changed, likely success)
   - Check for error overlays (Vision scan for "error", "sorry", "please try again")
   - Only if confidence < 0.70, invoke L3 LLM

3. **Implement `ensure_real_tab()`-equivalent for Electron apps** (VS Code, Slack, Discord, Cursor, Figma all use Chromium). T2 should:
   - Enumerate open windows via `chrome://inspect/#targets` or remote debugging port
   - Filter out internal pages (devtools, extensions)
   - Attach to the active user window
   - Re-attach on stale session (like daemon.py:184–186)

4. **Event buffering for Electron apps:** VS Code, Cursor (both Electron) emit keyboard events, focus changes, file saves as Window events. CDP events buffer them. Build T2's verifier to inspect `Page` + `Network` events post-action, not just screenshot.

5. **Browser recovery branches (B2-for-CDP):**
   - B1 (unchanged): Re-run action on T1 (AX for native, hybrid)
   - **B2_CDP_RETRY:** Re-run action on T2 with fresh screenshot + new coordinate calculation
   - B3 (unchanged): Try T3 AppleScript (if not already tried)
   - B4, B5: Vision/Pixel fallback

### B. Cross-Cutting Improvements (Translate Browser-Harness to Native Apps)

**Pattern 1: Coordinate Acts Default → Per-Tier Coordinates**

Browser-harness uses **compositor-level `Input.dispatchMouseEvent`** because it passes through all DOM layers. cua-maximalist equivalents:

- **T1 (AX):** `AXUIElement.performAction(kAXPress)` on element = DOM click equivalent. For reliable clicks: use **C1 SLEventPostToPid** (HID-level, passes SIP) to post `CGEvent.createMouseEvent(pos, kCGEventLeftMouseDown/Up)` to target app PID. This is the AX analogue of "compositor click"—happens at the OS event queue level, no app-level interception.
  
- **T3 (AppleScript):** `click at {x, y}` via System Events. Less reliable than C1 but matches browser-harness's coordinate-first philosophy (no DOM traversal needed).

- **T4 (Vision):** Bounding boxes from VNRecognizeTextRequest + VNImageRequestHandler → coordinates. Then use C1 or C3 (CGEvent) to act. Fallback model ShowUI-2B if UI-TARS-1.5 coord quantization bug (mlx-vlm #330) hits.

- **T5 (Pixel):** MLX UI-TARS or ShowUI grounding → coordinates directly. Then C1 or C3 post. This is already native pixel-to-coordinate, no DOM read.

**Pattern 2: Screenshot + Deterministic Verification First**

Like browser-harness (SKILL.md:128–129), every cua-maximalist action should:

```
Pre-action:  snapshot AX tree + screenshot + compute hashes
Act:         single-channel (T1→C1, T2→C5, T3→C4, T4→C1, T5→C1)
Verify:      post-snapshot AX + screenshot + compare hashes
   If dAX hash matches + pixel hash <5% delta → SUCCESS (deterministic)
   Else if L0 (Apple FM 3B) confidence >0.85 on error class → FAILURE
   Else if L1 (ensemble rule: 2/3 of {AX, pixel, L0}) agree → SUCCESS/FAILURE
   Else → ask L3 (Opus) or retry B-branch
```

This mirrors browser-harness's "screenshot-verify" loop but applies it to all translators, not just T2.

**Pattern 3: Event Buffering per Translator**

Browser-harness buffers CDP events (Page.loadEventFired, Page.javascriptDialogOpening, etc.) in a 500-entry deque. Native-app equivalents:

- **T1 (AX):** Subscribe to `AXObserver` push events (kAXValueChanged, kAXMenuOpened, kAXChildrenChanged, etc.). Buffer into deque, let verifier inspect post-action.

- **T3 (AppleScript):** No push events; use polling. But cache the last N app states (window title, frontmost status, visible buttons). On action failure, compare current state to pre-action to detect what changed.

- **T4/T5:** No app-level events. Use pixel/Vision diffs.

**Pattern 4: Session/Target Routing (Per-App)**

Browser-harness routes `Target.*` (browser-level) vs. session-scoped calls. Native apps:

- **T1 (AX):** Process-level vs. element-level. `AXUIElementCreateApplication(pid)` is "browser-level" (get the app). `AXUIElementCopyAttributeValue(element, kAXValue)` is "session-level" (get element state).

- **T3 (AppleScript):** App-level (`tell application "Slack"`) vs. window/element-level (`tell window 1 of application "Slack"` → `click button "Send"`).

File structure in cua-maximalist:
```
overlay/ipc/  — per-translator protocol routing (like daemon.py's meta="..."/"method" split)
overlay/verifiers/  — L0-L2 ensemble
overlay/translators/  — each returns canonical Action
overlay/recovery/  — B1-B5 branches
overlay/cassettes/  — episodic memory (JSON Lines)
overlay/recipes/  — site/app-specific patterns (domain-skills equivalent)
```

### C. What to Deprecate / Simplify

**DO NOT ATTEMPT:**

1. ❌ **Recursive AX tree walks.** CLAUDE.md hard rule: max 3 levels. Safari's AX tree is 15–20s to fully enumerate. Use **depth-limited snapshots** (root → visible children → their children). Cache tree generation number (macOS 12+) to detect stale snapshots.

2. ❌ **AX polling at >20 calls/sec.** cmux #2985: stalls Cocoa app's main thread. Use **push events via AXObserver** (subscribe once, listen for diffs). For apps without AX support (old Carbon/legacy), accept latency trade-off.

3. ❌ **LLM as verifier default.** Intrinsic self-correction is 16–27% accurate (papers 2601.00828, 2412.14959). Use **external oracle:** deterministic ensemble first, LLM only when confidence < 0.30.

4. ❌ **Destructive actions on multiple channels simultaneously.** Send/submit/delete should be **single-channel only**. Race them for selection/navigation, never for finality. Browser-harness doesn't race `goto()`, neither should cua-maximalist race `click_delete_button()`.

5. ❌ **Per-action retry loops in the overlay.** Retry logic belongs in **LangGraph nodes** (langgraph-checkpoint-postgres state). The overlay is stateless; the graph is durable.

---

## Concrete File Paths & Changes for CUA-Maximalist

### 1. **New: Coordinate Click Abstraction**

**File:** `/cua-maximalist/overlay/actions/coordinate_click.py` (new)

```python
# All translators should emit this canonical action for click, scroll, type
class CoordinateAction(Pydantic BaseModel):
    x: int
    y: int
    y: int
    action_type: Literal["click", "scroll", "type"]  # unified
    channel: Literal["c1_sl_event", "c2_ax", "c3_cgevent", "c5_cdp_input"]
    fallback_channel: Optional[Literal["c1_sl_event", "c2_ax", "c3_cgevent", "c5_cdp_input"]]
    verify_post: bool = True  # screenshot + dHash post-action
```

### 2. **Enhance: Verifier Ensemble (L0-L2)**

**File:** `/cua-maximalist/overlay/verifiers/ensemble.py` (expand)

```python
# Current: likely only L3 (Opus LLM)
# Add:
class L0Verifier:  # Apple FM 3B binary classify
    def verify(self, pre_state: UISnapshot, post_state: UISnapshot, action: Action) -> VerifyResult:
        # "Is element now visible?" "Is error dialog open?" "Is value changed?"
        # ~50-200ms per call, free, ANE-accelerated
        
class L1Verifier:  # Ensemble rules (AX subtree hash + pixel dHash + L0 agree)
    def verify(self, ...) -> VerifyResult:
        ax_match = pre.ax_hash == post.ax_hash  # no change = fail
        px_match = abs(pre.px_dhash - post.px_dhash) < 5  # <5% pixel delta
        l0_conf = l0.verify(...).confidence
        # Majority vote: if 2/3 agree, return that; else abstain for L3
```

### 3. **New: AXObserver Push Event Subscription**

**File:** `/cua-maximalist/overlay/ax/observer.py` (new)

```python
# Replaces AX polling with push events (like daemon.py event tap)
class AXObserverManager:
    def __init__(self):
        self.events = deque(maxlen=500)  # ring buffer
        self.observer = None
        
    async def subscribe(self, app_pid: int, notifications: List[str]):
        # Create AXObserver, register for kAXValueChanged, kAXMenuOpened, etc.
        # Callback appends to self.events
        
    def drain_events(self) -> List[AXEvent]:
        # Like daemon.py:46
        out = list(self.events)
        self.events.clear()
        return out
```

### 4. **Refactor: Verifier Integration Point**

**File:** `/cua-maximalist/overlay/orchestrator/race_verifier.py` (modify)

Current flow (assumed):
```
translator → action → channel.execute() → [maybe retry]
```

New flow (adopt from browser-harness):
```
translator → action → 
  {pre: snapshot()}  →
  channel.execute() →
  {post: snapshot()}  →
  L0(pre, post, action) → {confidence, verdict}
    if confidence > 0.85 → return verdict
    else → L1(pre, post, action, L0_result)
      if L1_agreement >= 2/3 → return verdict
      else → B_branch_or_L3
```

### 5. **New: Recipe Capture**

**File:** `/cua-maximalist/.planning/recipes/<app_name>/<action>.md` (populate after B1-B5 v1 ships)

Template:
```markdown
# <App Name> — <Action>

## Confirmed selectors / coordinates (field-tested 2026-<date>)

### Via T1 (AX)
- **Button "Submit":** `AXUIElement(role=kAXButton, title="Submit", parent_role=kAXDialog)`
- **Text field "Email":** selector `.email-input`, or by aria-label "Email Address"

### Via T2 (CDP/Electron)
- **Button "Submit":** `[class*="submit"]` or role="button"

### Via T3 (AppleScript)
- Not typical for this app

### Via T4 (Vision)
- Bounding box from OCR "Submit" text

### Via T5 (Pixel)
- UI-TARS grounding 94% confidence on dialog submit button

## Waits needed
- After menu open: 300ms (menu items render asynchronously)
- After file upload: 2s (S3 preflight)

## Gotchas
- App freezes on some file types — use try/catch
- Dialog title sometimes has emoji — filter via regex
```

### 6. **Modify: Cassette Schema**

**File:** `/cua-maximalist/overlay/cassettes/schema.py` (ensure captures all B-branch info)

```python
class CassetteStep(BaseModel):
    step_idx: int
    task_hash: str  # e.g., sha256 of task prompt
    
    hoare_pre: dict  # {url, ax_tree_hash, pixel_dhash, app_state}
    action_canonical: CoordinateAction
    channel_used: str  # "c1_sl_event", "c2_ax", etc.
    hoare_post: dict
    
    success: bool
    verifier_confidence: float  # L0 or L1 result
    recovery_branch: Optional[str]  # "B1" if re-ran T1, etc.
    
    screenshot_pHash: str  # phash for template match
    ax_subtree_hash: str
    healed_selectors: List[str]  # new selectors discovered during healing
```

### 7. **Modify: DragGraph State Node**

**File:** `/cua-maximalist/overlay/graph/nodes.py` or `/cua-maximalist/schema/action_node.py` (expand)

Currently (assumed): LangGraph node for each translator.

Add to each node's exit:
```python
async def execute_action(state: State) -> State:
    action = state.action
    
    # PRE-SNAPSHOT
    pre_snapshot = await take_snapshot(action.app_pid, action.window_id)
    state["pre_snapshot"] = pre_snapshot
    
    # CHANNEL EXECUTE
    try:
        result = await execute_on_channel(action, state.primary_channel)
        state["channel_result"] = result
    except Exception as e:
        state["channel_error"] = str(e)
        return state  # B-branch picks it up
    
    # POST-SNAPSHOT + VERIFICATION
    post_snapshot = await take_snapshot(action.app_pid, action.window_id)
    state["post_snapshot"] = post_snapshot
    
    verdict = await ensemble_verify(pre_snapshot, post_snapshot, action)
    state["verify_result"] = verdict
    
    # RECORD CASSETTE
    await record_cassette_step(state, verdict, primary_channel)
    
    return state
```

---

## Summary: What Browser-Harness Does Best

| Pattern | Browser-Harness Implementation | CUA-Maximalist Analogue | Benefit |
|---------|---|---|---|
| **Coordinate acts** | `Input.dispatchMouseEvent` (compositor) | C1 SLEventPostToPid (HID) | Passes through all layers; no DOM/AX interception |
| **Verify before retry** | Screenshot + dHash vs. pre-screenshot | AX tree hash + pixel dHash + heuristics | Cheaper than LLM; deterministic |
| **Event buffer** | 500-entry deque on CDP events | AXObserver push events + ring buffer | Don't poll; react to app changes |
| **Session routing** | `Target.*` (browser-level) vs. session-scoped | PID/app-level vs. element-level | Avoids stale-session bugs |
| **Async with timeouts** | `asyncio.wait_for(..., timeout=5)` | `asyncio.wait_for(asyncio.to_thread(...))` | Prevent hangs |
| **Stale recovery** | `ensure_real_tab()` + re-attach | Restart AX observer + retry from cassette | Automatic, no supervisor |
| **No manager layer** | ~600 lines, agents edit mid-task | <2500 LOC overlay, LangGraph owns orchestration | Simplicity + extensibility |
| **Domain skills (recipes)** | Agents author, PR back | Agents author via cassette synthesis, PR recipes | Self-improving ecosystem |

Browser-harness is the **reference implementation for deterministic browser healing**. cua-maximalist should copy its core philosophy—**coordinate acts, verify deterministically, buffer events, no manager framework**—and apply it uniformly across all 5 translators and 5 channels. The result: a computer-use system that is as reliable for native macOS apps as browser-harness is for web automation.

