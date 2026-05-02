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
