# Google Chrome — general CDP control

> Field-tested 2026-05-02 against macOS 26 + Chrome 144.

## Coexistence with browser-harness

If Akeil has the browser-harness daemon running (`browser-harness ...`),
its Electron-based Chrome instance binds one of T2's probe ports
(usually 9223). cua-maximalist's T2 then probes 9222→9225 in order
and may attach to browser-harness's Chrome — wrong instance. The
`CUA_T2_CDP_PORT_OVERRIDE` env var pins the probe to a single port;
the cdp-chromium e2e test sets it. For interactive use, stop
browser-harness before running cua-maximalist on Chrome.

## Launch with remote debugging

Chrome refuses `--remote-debugging-port` when the requested
`--user-data-dir` is locked by another running Chrome instance (the
user's daily browsing). Always pass a fresh temp profile:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \    # F-bug F15: Chrome listens on
                                             # [::1] only by default; httpx to
                                             # 127.0.0.1 then fails
  --user-data-dir=/tmp/chrome-cua-XXX \
  --no-first-run --no-default-browser-check \
  --headless=new --disable-gpu \
  https://example.com
```

## CDP probe ports

cua-maximalist's T2 only probes `9222-9225` (cdp_use limitation: see
`cua_overlay/translators/t2_cdp.py:CDP_PROBE_PORTS`). Bind your test
launcher to one of these. The fixture in
`tests/integration/test_cdp_chromium_e2e.py` iterates and kills any
stale process holding the others.

## DevTools targets — what's a "real page"

Chrome's `Target.getTargets` returns 4 categories:
- `type=page` + URL like `https://...` → real user content (use this)
- `type=page` + URL `chrome://omnibox-popup` → the address-bar dropdown,
  appears as a 1px hidden frame; **never attach to it**
- `type=page` + URL `chrome-extension://...` → installed extension
- `type=service_worker` / `background_page` → support workers

`CDPDaemon._is_real_page()` filters all the not-real categories.

## Stable patterns

- **Click any visible link by text**: T2's text-content fallback (added
  per browser-harness §G2) runs `Runtime.evaluate` over `a/button/input/
  [role=button]/[role=link]` and matches `innerText | textContent |
  ariaLabel | title`. Provide `TargetSpec(label="Sign in")`; no CSS
  required.
- **Get current page URL**: query the **page** WS (from `/json`), not
  the browser-level WS (from `/json/version`). `Runtime.evaluate` on the
  browser target returns nothing.
- **Headless Chrome registers no NSWorkspace bundle**: the `pid` is
  visible to PyObjC's `NSRunningApplication` but `bundleIdentifier()` is
  empty for the *helper* processes. Pass the parent PID.

## Traps

- **Stale CDP port**: if a previous test crashed leaving Chrome
  half-alive, port 9222 reports `bind() failed: Address already in use`
  but the prior Chrome is what answers `/json/version`. Kill all Chrome
  instances before a test (`pkill -9 -f "Google Chrome"`) and pick a
  port via `socket.bind("127.0.0.1", 0)` if you can.
- **Cold-launch latency**: Chrome can take 10-15s to bind the debug
  port on first launch (GPU init, profile setup). Poll up to 30s.
- **`--no-sandbox` is harmless on macOS** (sandboxing is OS-level), but
  required if you launch via SSH session.

## Path B — drive the USER'S running Chrome via CDP (browser-harness pattern)

When Akeil already has Chrome running with their tabs, sessions, and
logins, do NOT launch a fresh debug-port Chrome — you'd lose his
cookies and have to re-auth everywhere.

The right path is **CDP via the per-profile remote-debugging
checkbox** — same pattern as `github.com/browser-use/browser-harness`.
Once the checkbox is ticked on a profile, every future Chrome launch
on that profile auto-enables CDP. No relaunch flags. No fresh
profiles. Sticky forever.

### Preflight: detect whether CDP is already enabled

```bash
# Look for DevToolsActivePort in every Chrome profile dir.
# Its presence == CDP is on right now and the port is in the file.
find ~/Library/Application\ Support/Google/Chrome -maxdepth 2 \
     -name DevToolsActivePort 2>/dev/null
```

- File exists → read it: line 1 is the port (e.g. `9222`), line 2 is
  the `/devtools/browser/<uuid>` path. Connect via
  `ws://127.0.0.1:<port>/devtools/browser/<uuid>` (or hit
  `http://127.0.0.1:<port>/json/version` for the WebSocketDebuggerUrl).
  Skip directly to "Drive via CDP" below.
- File absent → run the one-time UI setup below.

### One-time setup: tick the chrome://inspect checkbox

On Chrome 144+ this is mandatory and must be done once per profile:

```
1. Activate Chrome (osascript or cua launch_app)
2. cmd+L to focus omnibox
3. Type chrome://inspect/#remote-debugging + return
4. Wait for the page to render (~1.5s)
5. Find the "Discover network targets" checkbox + tick it
6. Chrome shows an "Allow remote debugging" popup (per-attach since
   Chrome 144) — click Allow
7. Chrome may need to relaunch the renderer; wait until
   DevToolsActivePort appears in the profile dir (poll up to 30s)
```

The checkbox state persists in the profile's Preferences JSON. After
this one-time tick, every future Chrome launch on this profile
auto-enables CDP — no flags, no checkboxes, no popups.

### Drive via CDP (after preflight)

cua-maximalist's `T2 CDP` translator already knows how to talk CDP
(`cua_overlay/translators/t2_cdp.py`, probes ports 9222-9225). Once
DevToolsActivePort exists, T2 will pick it up automatically — no
extra setup on the cua side.

For raw use, the `cdp-use` library (vendored in browser-harness) is
the lowest-friction client:

```python
from cdp_use import CDPClient
client = await CDPClient.connect("ws://127.0.0.1:9222/devtools/page/<id>")
await client.send_raw("Page.navigate", {"url": "https://lu.ma/event"})
await client.send_raw("Input.dispatchMouseEvent", {
    "type": "mousePressed", "x": 400, "y": 300, "button": "left",
    "clickCount": 1
})
```

Coordinate clicks via `Input.dispatchMouseEvent` go through the
COMPOSITOR — they pass cleanly through iframes, shadow DOM, and
cross-origin frames that AX would lose.

### Self-heal: detect missing setup, fix it inline

If a CDP attach fails with "connection refused" but DevToolsActivePort
doesn't exist, the user has never ticked the checkbox. Don't bail —
walk them through the one-time setup above (or do it via AX clicks).
Once done, retry the CDP attach. After that point, every future
session is fast.

If CDP attach fails with "connection refused" but DevToolsActivePort
DOES exist, the port is enabling but not yet listening — poll for up
to 30 seconds (per browser-harness CLAUDE.md). Don't conclude broken.

### Fallback only — the AppleScript JS bridge

If CDP setup is impossible (managed-profile policy, locked-down
Chrome) the `mcp__cua-maximalist__page` tool routes through Chrome's
AppleScript JS bridge. Requires `defaults write com.google.Chrome
AllowJavaScriptFromAppleEvents -bool true` PLUS toggling View →
Developer → Allow JavaScript from Apple Events in the menu (the
defaults flag alone is NOT sufficient on Chrome 130+; tested
2026-05-02 — Chrome rejects with "Allow JavaScript from Apple
Events is not enabled" even with the defaults flag set). Use only
when CDP is genuinely unavailable.

### Preflight (idempotent — run before every Chrome session)

```bash
# 1. Check current state
defaults read com.google.Chrome AllowJavaScriptFromAppleEvents 2>/dev/null

# 2. If output is missing or 0, set the flag
defaults write com.google.Chrome AllowJavaScriptFromAppleEvents -bool true

# 3. Clean-quit Chrome so the new pref is loaded.
#    Session restore brings tabs back via "Continue where you left off"
#    (default-on for most users).
osascript -e 'tell application "Google Chrome" to quit'

# 4. Wait for the process to drop, then relaunch.
while pgrep -x "Google Chrome" > /dev/null; do sleep 0.5; done
osascript -e 'tell application "Google Chrome" to activate'
sleep 3   # let the session restore finish before the first JS call
```

Verify the bridge is live by running a tiny JS read against any tab:

```python
mcp__cua-maximalist__page(
  action="execute_javascript",
  javascript="document.title",
  pid=<chrome_pid>,
  window_id=<any_visible_chrome_window_id>,
)
```

If you get a real string back, the bridge is on. If you get
"Allow JavaScript from Apple Events is not enabled", the defaults
write didn't persist — Akeil may have a managed-profile policy
overriding it. Fall back to AX clicks (slow but works).

### Daily usage (no relaunch needed once flag is set)

The flag is sticky across Chrome restarts and Chrome version updates.
You only quit+relaunch the FIRST time you set the flag. After that,
preflight = `defaults read` and verify == `1`, that's it.

### What `page` lets you do that AX can't

- `execute_javascript` — fill multiple form fields in one round-trip
  via `document.querySelector('input[name=email]').value = '...'`.
  AX needs one click + type per field with focus races between them.
- `query_dom("a.event-card", attributes=["href"])` — get every event
  link's URL in one call. AX would walk hundreds of nodes.
- `get_text` — `document.body.innerText` of the full page. AX
  truncates at the WebArea boundary.

### Form-fill recipe (RSVP / signup forms)

```python
# 1. Navigate
page(action="execute_javascript",
     javascript='window.location.href = "https://lu.ma/some-event"')
# 2. Wait for hydration (Luma is React + lazy-mount; 2s is safe)
import time; time.sleep(2)
# 3. Fill all fields atomically
page(action="execute_javascript", javascript="""
(() => {
  const set = (selector, val) => {
    const el = document.querySelector(selector);
    if (!el) return false;
    const setter = Object.getOwnPropertyDescriptor(
      Object.getPrototypeOf(el), 'value'
    ).set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  };
  return {
    name:    set('input[name="name"]',    'Akeil Smith'),
    email:   set('input[name="email"]',   'asmithsrs04@gmail.com'),
    company: set('input[name="company"]', 'TheBasicsCompany'),
  };
})()
""")
# 4. Click submit by visible text — works through React onClick too
page(action="execute_javascript", javascript="""
(() => {
  const btn = [...document.querySelectorAll('button,a')]
    .find(b => /register|rsvp|submit/i.test(b.innerText));
  if (btn) btn.click();
  return btn ? 'clicked: ' + btn.innerText : 'no button found';
})()
""")
```

The `setter.call` + `dispatchEvent('input')` dance is critical for
React inputs — `el.value = x` alone doesn't notify React's state.

## Decision: when to use Path A (fresh debug port) vs Path B (user's Chrome)

```
USE PATH A (fresh port) WHEN          USE PATH B (user's Chrome) WHEN
────────────────────────────────────  ────────────────────────────────
running an integration test            need user's logged-in sessions
need clean profile / no extensions     RSVP'ing to events / form-fill
running headless on CI                  on sites where they have an
parallel test runs (each gets its       account
own profile)                            scraping behind login walls
                                        anything where their cookies
                                        matter
```
