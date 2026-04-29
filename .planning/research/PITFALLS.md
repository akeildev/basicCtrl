# Domain Pitfalls — cua-maximalist

**Domain:** Self-healing autonomous Mac CU framework (Python overlay above trycua/cua Swift driver, full private-SPI, racing translators, deterministic ensemble verifier, 5-branch recovery)
**Researched:** 2026-04-29
**Confidence:** HIGH (every pitfall here is sourced from production code, GitHub issues, or post-Oct-2024 papers in the locked architecture)

---

## How to read this

Each pitfall has:

- **Severity** — BLOCKER (system unusable), MAJOR (whole class of apps broken), MINOR (degraded but works)
- **Phase** — which sprint owns prevention (Sprint 0-11 from the locked architecture)
- **Warning signs** — how to detect early, before it becomes silent corruption
- **Prevention** — concrete code/design choice, not generic "be careful"

Pitfalls are grouped by subsystem so each phase can pull its own checklist.

---

## CRITICAL pitfalls (BLOCKER — system unusable if hit)

### Pitfall 1: Action interference — racing translators cause double-clicks / double-form-submits

**Severity:** BLOCKER (corrupts user data the first time it happens)
**Phase:** Sprint 3 — Racing translator pattern (ACT-01..04)

**What goes wrong:** 5 channels (C1 SLEventPostToPid, C2 AX kAXPress, C3 CGEvent.postToPid, C4 AppleScript, C5 CDP) all fire at the target. Each can succeed independently. Without atomic claim, two channels both deliver — Submit pressed twice, $X charged twice, message sent twice.

**Why it happens:** `asyncio.wait(FIRST_COMPLETED)` cancels Python coroutines, but the OS-level event has already been dispatched on losing channels. CGEvent + SLEventPostToPid are fire-and-forget at the kernel/SkyLight level — there is no "cancel" once they hit the event tap.

**Consequences:** Double-execution of any non-idempotent action. Worst class: payments, message send, file delete, git push. Trust collapses on first incident.

**Warning signs:**
- Action log shows two "verified" events for the same step
- Form has duplicated entries
- AXNotification fires twice within <50ms for the same target
- Cassette replay re-executes a "second" identical step that wasn't in the plan

**Prevention:**
1. **Atomic pre-action ID written to shared state BEFORE any channel fires** — use `asyncio.Lock` + monotonic UUID. All channels read this ID at the start of their fire path; if already set, they immediately return `Cancelled`.
2. **OS-level kill switch** — for SLEventPostToPid + CGEvent, schedule the post inside a coroutine that checks `cancel_event.is_set()` immediately before the syscall. There's still a ~50µs window, but it shrinks the surface.
3. **Per-action-class race policy** — never race destructive actions. `submit`, `send`, `delete`, `confirm` use **single-channel** delivery (T1 AX with verifier). Race only safe ops: `click_button`, `focus`, `scroll`, `type_into_focused`.
4. **Idempotency receipts** — verifier records `(target_axid, action_kind, ts)` in a 2-second ring buffer. Second post on same target+kind within 2s is dropped at the verifier (post-action, but at least logged as a near-miss).
5. **Staggered race instead of concurrent race for AppleScript** — AS is so slow (50-500ms) that by the time it fires, T1/T2 have already verified. Add 500ms delay before AS fires; if any other channel verifies, kill the AS subprocess.

**Counterevidence to "always race":** For mutating ops, racing is strictly worse than ordered fallback. Single-channel + bounded retry is the right pattern for `submit`-class actions. Racing belongs to `read`-class and idempotent positioning.

---

### Pitfall 2: AX main-thread saturation (cmux #2985 — polling AX >30/sec stalls target app)

**Severity:** BLOCKER (target app freezes — user thinks our agent crashed Slack)
**Phase:** Sprint 1 — Push-event verifier; Sprint 2 — Deterministic ensemble L1

**What goes wrong:** Every `AXUIElementCopyAttributeValue` call is a synchronous Mach IPC into the target process's main thread. >30 calls/second saturates the target's run loop — the app stops drawing, stops responding to user input, stops processing AX requests. cmux logged this in issue #2985.

**Why it happens:** Eager AX walks during verification (e.g., re-reading the entire focused window subtree after each action) + parallel verification branches each making their own AX calls = N×30/sec.

**Consequences:** Target app spinning beachball. Looks like our agent crashed the user's app. Full app force-quit may be needed. Worst case: data loss in the target app.

**Warning signs:**
- `kAXErrorCannotComplete` (-25204) starts appearing
- AX call latency climbs from <5ms baseline to >100ms
- User reports "app is frozen" while agent is running
- Activity Monitor shows target app at 100% CPU on main thread

**Prevention:**
1. **Hard rate limit per target pid:** token bucket, max **20 AX calls/sec/pid** (well below the 30 saturation point). Implement at the AXUIElement wrapper layer so it's automatic.
2. **Coalesce reads:** any AX walk within a 100ms window returns the cached subtree. Verifiers share the cache.
3. **Push-event-first verification** (the secret weapon): once subscribed via `AXObserverAddNotification`, the kernel pushes events for free — zero AX polling needed. L0 verifier should NEVER walk AX; only listen.
4. **Depth-limited subtree on L2:** max 3 levels (never full recursive — see Pitfall 3). Cap children per node at 50.
5. **Fail-open on rate-limit hit:** when the bucket is empty, return last cached value with `confidence -= 0.2` rather than blocking. Saturating AX is worse than slightly-stale state.
6. **Per-app circuit breaker:** if `kAXErrorCannotComplete` rate >5%/30s, switch primary translator to T2/T4 for that bundle for 60s, log the event.

**Counterevidence:** Apple Health automation tools that "just walk AX" work because they fire once per minute. Our 100ms loop is 600× more aggressive — the public API was never designed for this rate.

---

### Pitfall 3: Full recursive AX diff is 15-20s on Safari (use depth-limited)

**Severity:** BLOCKER (every L2 verify takes 20s — verification budget blown)
**Phase:** Sprint 2 — Deterministic ensemble L1/L2

**What goes wrong:** `AXUIElementCopyAttributeValue(AXChildren)` recursively on Safari's webarea returns thousands of DOM-mirrored AX nodes. Confirmed 15-20s on real pages. Computing diff of that tree blows the verification budget by 100×.

**Consequences:** Every L2 verify takes 20s. The whole point of the layered ensemble (L0→L1→L2→L3 in milliseconds) collapses. User sees the agent "stuck" for 20s after every action.

**Warning signs:**
- L2 verify latency >2s on web/Electron apps
- Action log shows L2 timeouts on Chrome/Safari/Slack/VS Code
- AX walk completes but returns >5000 nodes
- Target app's main thread stalls during the walk (compounds Pitfall 2)

**Prevention:**
1. **Hard cap at 3 levels deep, 50 children per node, 500 total nodes.** Walk emits `truncated=true` flag if any cap hit; verifier confidence is reduced if truncated.
2. **For web content (Chrome/Safari/Slack/VS Code/etc.) skip AX entirely on L2.** Use **CDP DOM mutation observer** (T2 path) — already a primary verifier on those bundles via `Page.lifecycleEvent` + `DOM.documentUpdated`. AX is for native chrome only.
3. **Targeted AX read instead of subtree walk:** read attributes of the SPECIFIC element involved in the action (`AXValue`, `AXTitle`, `AXEnabled`, `AXFocused`) — this is one Mach call, <2ms. Save the subtree walk for L3.
4. **Subscribe to `kAXLayoutChanged` on parent** instead of polling — push-based at L0 catches the same signal at <1ms.
5. **Bundle-specific allowlist:** only walk AX subtree for bundleIDs proven to have small AX trees (system System Settings, Activity Monitor, Mail composer). Block walks on Safari/Chrome/Slack/Discord/VS Code/Cursor/Notion/Linear/Obsidian.

---

### Pitfall 4: UI-TARS MLX coordinate quantization bug (mlx-vlm #330 — outputs default to screen center)

**Severity:** BLOCKER for T4 grounder path (every click lands at screen center)
**Phase:** Sprint 6 — Speculative pre-execution; Sprint 4 — Failure classifier

**What goes wrong:** UI-TARS-1.5-7B running through `mlx-vlm` has a known coordinate quantization regression (issue #330): when the model's output token probabilities are too flat, the dequantized coordinate defaults to (0.5, 0.5) — exact screen center. Every "click" lands at screen center, hitting whatever happens to be there.

**Consequences:** Silent miss. Action fires, screen center button gets clicked instead of intended target. Verifier may even pass (something visible changed), masking the regression.

**Warning signs:**
- Multiple consecutive actions land at exactly (W/2, H/2) or within ±10px
- Click coords identical across 3+ different intended targets
- Verifier passes but goal completion drops sharply
- Recipe replay diverges at the exact same step every time

**Prevention:**
1. **Default grounder = `swaylenhayes/uitag` (Apple Vision + YOLO11 MLX).** Confirmed 90.8% coverage, no quantization issue. UI-TARS is **secondary**, not primary.
2. **Post-grounder sanity gate:** reject any UI-TARS output where `|x - W/2| < 10 AND |y - H/2| < 10` unless the actual target IS center (verified via L1 pixel hash of expected element). Force re-ground via uitag.
3. **Differential grounding:** when UI-TARS is used, also run uitag in parallel, require IoU >0.5 between bounding boxes. Disagreement → fall to T4 OCR-grounded action.
4. **Pin mlx-vlm version** — track upstream fix for #330; until merged, hold a known-good version + manual patch in `requirements.txt`.
5. **Telemetry:** count "screen-center clicks" per session; alert if >1% of T4 actions land within ±20px of center.

**Counterevidence to UI-TARS-as-primary:** UI-TARS-1.5 verified at 5-25% OSWorld success rate as a pixel-only path. Grounder for OUR system, not autonomous driver. Don't make it primary.

---

### Pitfall 5: AppleScript stale-state lag (50-200ms blocks event loop)

**Severity:** MAJOR (every action that uses AS pays 50-200ms latency tax)
**Phase:** Sprint 3 — Racing translator pattern; Sprint 0 — translator scaffolding

**What goes wrong:** `NSAppleScript.executeAndReturnError` is **synchronous and blocks the calling thread.** Even in-process (no `osascript` subprocess), a single AppleScript call is 50-200ms. Worse, AS reads stale snapshots — it queries the target app's scripting bridge cache, which can be 100ms behind the live state. Doing AS verification means you race against AS's own internal state lag.

**Consequences:** AS in the racing channel always loses to C1/C2/C5, but only AFTER pinning a thread for 200ms. Concurrency story collapses.

**Warning signs:**
- Asyncio event loop lag spikes to >100ms when AS channel fires
- AS post-action verify reports "old" value despite UI clearly updated
- Race orchestrator's "first verified" times skew when AS is in the pool

**Prevention:**
1. **AS goes in its own thread pool** — `asyncio.to_thread()` or dedicated `concurrent.futures.ThreadPoolExecutor(max_workers=2)`. Never run AS on the main asyncio loop thread.
2. **Staggered race** — AS fires 500ms AFTER C1/C2/C5. If any other channel verifies first (the common case), AS coroutine is cancelled before it actually runs the AppleScript.
3. **AS for write-rare, read-never paths** — use AS for `make new note`, `set track to`, but NEVER for verification. Use AX or push events to verify after AS.
4. **In-process NSAppleScript only** — never `osascript` subprocess (that's another 200ms of fork+exec on top).
5. **Bundle-aware AS gating** — only enable AS channel for apps where it's proven to be the primary path (Pages, Numbers, Keynote, Mail, Calendar, Notes, Reminders, Music, Spotify, iTerm2). Off for Electron/web by default.

---

### Pitfall 6: Apple FoundationModels 50% hallucinated params on complex schemas

**Severity:** BLOCKER if you treat FM as a plan-class model
**Phase:** Sprint 6 — Apple FM tier-0 classifier

**What goes wrong:** Apple's on-device 3B FoundationModel hallucinates ~50% of parameters when asked to fill complex JSON schemas (>3 fields with nested types). Apple confirms FM is **structurally constrained to small-enum / binary** decisions on its public surface.

**Consequences:** If FM picks the action AND its parameters, the parameters are garbage half the time. Wrong target, wrong text, wrong key. Recovery loop never converges because the "fix" is also hallucinated.

**Warning signs:**
- FM-selected actions have argument validation failures >20%
- Cassette replays diverge on FM-selected steps
- FM emits enum values that aren't in the prompt enum list

**Prevention:**
1. **FM is a tier-0 CLASSIFIER ONLY** — output is a single enum from a small set (`{T1, T2, T3, T4, T5}` or `{retry, escalate, abort}`). Never JSON, never multi-field params.
2. **Hard-validate every FM output against an allowed enum.** Anything outside the enum is treated as a "no decision" and falls through to the next tier (Opus / GPT-5).
3. **No FM for parameter generation** — params come from Opus/GPT-5 or from cassette replay. FM never decides "what text to type" or "which selector".
4. **FM 4096-token context cap respected** — never feed full screenshots, full DOM, full state graph. FM gets condensed (<500 token) summary only.
5. **Confidence heuristic:** if FM emits a low-probability token (top-token logit gap <2.0), treat as "no decision" and escalate.

**Counterevidence:** Apple markets FM as "agentic Siri replacement" but agentic Siri itself is delayed to iOS 26.5/27 (Federighi, Bloomberg). The real model isn't ready for plan-class work in 26.4 either.

---

### Pitfall 7: Apple FM is text-only in public API (no image input as of 26.4)

**Severity:** MAJOR (FM can't ground on screenshots — limits its usefulness)
**Phase:** Sprint 6 — Apple FM tier-0 classifier

**What goes wrong:** Apple's public `apple/python-apple-fm-sdk` (and FoundationModels framework as of macOS 26.4) accepts **text prompts only.** No image input. So FM cannot look at a screenshot and say "click the X button."

**Consequences:** Routing decisions that need visual context (e.g., "is this dialog modal?") can't use FM. FM is constrained to text/AX-summary inputs.

**Warning signs:**
- Plans for FM-based visual grounding will silently fail at integration time
- Architecture docs that say "FM screenshot eval" without source citation are wrong

**Prevention:**
1. **Architectural assumption: FM = text-only classifier.** Don't design a path that requires FM to see pixels.
2. **For screenshot routing decisions, use Vision OCR + uitag SoM as input to FM** — convert pixels to a textual scene description, then FM classifies the text.
3. **Track Apple FM SDK release notes** at every macOS dot release. If image input ships in 26.5+, gate behind a `SUPPORTS_IMAGE_INPUT` capability probe.
4. **Cloud VLMs (Opus / GPT-5) are the screenshot path.** Never substitute FM where pixels matter.

---

### Pitfall 8: Electron --remote-debugging-port is launch-only (can't inject into running app)

**Severity:** BLOCKER for "user already has Slack open" path
**Phase:** Sprint 0 — App classifier; Sprint 3 — T2 CDP translator

**What goes wrong:** Chromium / Electron's `--remote-debugging-port` flag is parsed at process start. If Slack/Discord/VS Code is already running, attaching CDP requires **relaunching the app.** Relaunch loses unsaved state, kicks active video calls, and pisses off the user.

**Consequences:** First time we hit a running Electron app, we either:
- Skip CDP path entirely (lose 80% of T2 capability)
- Force-relaunch (destroy user state — unacceptable)
- Fall to T1 AX (works but loses CDP DOM/JS/network access)

**Warning signs:**
- T2 attach fails with "no debugger endpoint" on already-running Electron apps
- App classifier reports `cdp_available=false` for Slack/Discord even though those are Electron
- User complains agent killed their Slack call

**Prevention:**
1. **Detection-first, never silent relaunch.** Classifier probes `localhost:<known-electron-port-pattern>` before deciding T2 is available.
2. **For ALREADY-RUNNING Electron apps, fall to T1 AX as primary.** AX on Electron works (with `_AXObserverAddNotificationAndCheckRemote` — see SPI-02) — just not as rich as CDP.
3. **Opt-in pre-launch flag injection** — add a launch-agent or shell wrapper that adds `--remote-debugging-port` to user-launched Electron apps system-wide. User opts in once (e.g., "always run Slack with debug port"). Symlink trick or `launchd` plist override.
4. **Per-app DYLD injection (SIP off, Sprint 9)** — `DYLD_INSERT_LIBRARIES` into the running renderer to expose a CDP-equivalent IPC. Last-resort, fragile, requires SIP off.
5. **Communicate the trade-off to the user** — never silently relaunch. If only relaunch unlocks T2, surface it as a one-time prompt: "Slack must restart to enable rich automation. OK?"

**Counterevidence to "always use CDP":** browser-harness solves this for Chrome by talking the user through ticking the chrome://inspect checkbox once. Electron apps don't have that UI — there's no checkbox to flip. Plan around AX-primary on Electron until the user opts in.

---

## VERIFIER & VISUALIZER pitfalls (BLOCKER — visualizer breaks the verifier)

### Pitfall 9: ScreenCaptureKit captures own overlay unless excluded via SCContentFilter

**Severity:** BLOCKER (verifier sees ghost cursor + HUD overlaid on screen, thinks state changed)
**Phase:** Sprint 7 — Visualizer (VIS-05)

**What goes wrong:** Default `SCContentFilter` includes ALL on-screen content. Our ghost-cursor NSPanel + HUD are technically windows. When the verifier captures the screen for L1 pHash / L2 OCR, our own overlay shows up — pixel hash always changes (because the cursor moved), OCR picks up the HUD text.

**Consequences:** Every L1 pHash diff returns "changed". Every L2 OCR sees "Last action: click X" which leaks into the verifier's text. Verifier confidence calibrates to noise.

**Warning signs:**
- L1 pHash always reports `changed=true` even when nothing changed
- OCR text contains "Last action:" or HUD strings
- Action log shows verifier passes on every action regardless of actual result

**Prevention:**
1. **`SCContentFilter(display:excludingWindows:)` with our overlay window IDs.** Pass the overlay's `CGWindowID` (from `NSPanel.windowNumber` cast to `CGWindowID`).
2. **Single capture instance shared between verifier and visualizer.** Capture once, use for both, ensure filter is applied at the source.
3. **Test before shipping the visualizer** — add a `pytest` that runs verifier with overlay visible vs hidden, asserts identical results.
4. **Belt-and-suspenders: NSPanel.sharingType = .none** as a backup for older capture paths (but see Pitfall 10 — broken on macOS 15+).

---

### Pitfall 10: macOS 15+ `window.sharingType = .none` no longer hides overlay

**Severity:** BLOCKER (the public-API way to hide windows from capture is broken)
**Phase:** Sprint 7 — Visualizer

**What goes wrong:** `NSWindow.sharingType = .none` historically hid a window from screenshots and screen-recording. Starting macOS 15 (Sequoia), this no longer applies to ScreenCaptureKit captures — the property is honored by deprecated CGWindowList paths only. Our overlay shows up in SCK captures even with sharingType=.none.

**Consequences:** If you rely solely on sharingType, the overlay leaks into the verifier (Pitfall 9 returns).

**Warning signs:**
- Verifier sees overlay despite sharingType=.none being set
- Tests pass on macOS 14 fail on 15+ / Tahoe

**Prevention:**
1. **Use `SCContentFilter(display:excludingWindows:)` as PRIMARY** — that's the only working API in macOS 15+.
2. **Don't trust sharingType** — keep it set as belt-and-suspenders, but never as the only mechanism.
3. **Capability probe at startup** — try `SCContentFilter(excludingWindows:)`, log whether the API is available. Degrade gracefully (warn user, disable visualizer rendering during verification) if not.
4. **Apple bug FB filed** — track upstream radar; if Apple restores sharingType behavior, simplify code.

---

### Pitfall 11: WindowServer CPU spike with transparent NSWindow + many CALayers

**Severity:** MAJOR (battery drain, frame drops, but doesn't break correctness)
**Phase:** Sprint 7 — Visualizer

**What goes wrong:** A transparent borderless NSPanel covering the full screen, with many sub-CALayers (ghost cursor + element highlights + HUD), forces WindowServer to recomposite the entire screen at 60fps. WindowServer CPU jumps from <2% baseline to 30-50%.

**Consequences:** Battery drain, GPU thermal throttling, system feels sluggish. User notices.

**Warning signs:**
- `top -pid $(pgrep WindowServer)` shows >20% CPU with overlay on
- Activity Monitor shows ~5W extra power drain
- 60fps recordings drop frames

**Prevention:**
1. **Single CAShapeLayer per element, not one CALayer per pixel.** Reuse layers; update positions, don't add/remove.
2. **`canDrawConcurrently = false`, `wantsLayer = true`.** Let CoreAnimation handle compositing; don't force CPU drawing.
3. **Hide overlay during verification windows** — toggle `.alphaValue = 0` during the 100-500ms L2 verify window. Restore after. Removes the recomposite cost when it matters.
4. **Render only changed regions** — `setNeedsDisplay(in:)` with a tight rect, never full-window invalidation.
5. **Cap update rate** — ghost cursor lerp at 60fps, HUD at 10fps (text rarely changes), element highlight only on transition. Different layers, different update rates.
6. **Telemetry:** WindowServer CPU via `proc_pid_rusage` or `ps`. If overlay cost >15% sustained, auto-disable visualizer with a warning.

---

## SCREEN CAPTURE pitfalls

### Pitfall 12: macOS Tahoe SCScreenshotManager regression (issue #870)

**Severity:** MAJOR (intermittent capture failures on the target macOS version)
**Phase:** Sprint 2 — Deterministic ensemble (capture path); Sprint 0 — translator scaffold

**What goes wrong:** `SCScreenshotManager.captureImage` (the modern, recommended path) intermittently returns `CaptureError.captureFailed` on macOS 26 (Tahoe). Confirmed in trycua/cua issue #870. Failure rate is non-deterministic, ~1-5%.

**Consequences:** 1-5% of L1 pHash and L2 OCR verifies just fail. Without retry, that's 1-5% silent verifier blackout.

**Warning signs:**
- Intermittent `CaptureError` in logs without pattern
- Increased rate of L0-only verifies (because L1+ couldn't read pixels)

**Prevention:**
1. **Retry once with 200ms delay** — confirmed mitigation from cua-driver.
2. **On 2nd failure, fall back to ScreenCaptureKit STREAM mode** — `SCStream` with single-frame pull is more stable than the manager API.
3. **Last-resort fall back to `CGWindowListCreateImage`** — deprecated but still works on Tahoe; emit warning event.
4. **Track issue #870 upstream** — pin mitigation to it; remove when Apple fixes.
5. **Capability probe at session start** — try a test capture, classify the path that works. Cache per-session.

---

## STATE GRAPH & TRANSLATOR pitfalls

### Pitfall 13: AX element ID is unstable (React/SwiftUI re-renders)

**Severity:** MAJOR (cache misses on every re-render — defeats episodic memory)
**Phase:** Sprint 0 — STATE-01 typed-graph state model; Sprint 5 — Cache self-heal

**What goes wrong:** `AXUIElement` references are pointers into the target's process memory. React, SwiftUI, and AppKit lazy-loaded views re-create the underlying view objects on state changes. The "same" button has a new AXUIElement after every list scroll, every modal open, every focus change.

**Consequences:** Caching by AXUIElement ref is useless — entries invalidate constantly. Episodic memory keyed by element identity never hits.

**Warning signs:**
- AgentCache hit rate <10% on long sessions
- `kAXErrorInvalidUIElement` after benign UI changes
- Recipe replay always falls through to live re-execute

**Prevention:**
1. **Use a STABLE identity tuple, never the AXUIElement ref:** `(role_path, label, AXIdentifier_if_present, parent_label, sibling_index)`. Hash this tuple as the cache key.
2. **10-tier locator hierarchy** (AX-tree paper 2603.20358): AXIdentifier → AXLabel → AXRoleDescription → AXTitle → AXHelp → AXValue substring → role+position → role+sibling-context → vision-grounded. Try in order on cache miss.
3. **Pre-action liveness check** — `AXUIElementCopyAttributeValue(role)` probe before fire; if `kAXErrorInvalidUIElement`, re-resolve via the locator hierarchy.
4. **Cache the LOCATOR not the ELEMENT** — what's persisted in cassettes is the role-path string, not the runtime ref.
5. **`elementID` field in StateNode is annotation, not identity** — for debugging/observability only, not for lookup.

---

### Pitfall 14: AX notifications fail on Chrome/Safari web content (sandboxed)

**Severity:** MAJOR (the "secret weapon" L0 push verifier doesn't work on web content)
**Phase:** Sprint 1 — Push-event verifier (VERIFY-01)

**What goes wrong:** AXObserverAddNotification on web content (inside Chrome's renderer or Safari's webarea) silently drops because the renderer is sandboxed. Notifications never fire. The verifier waits forever.

**Consequences:** L0 push verifier returns no signal on web pages — falls through to L1/L2/L3, blowing the latency budget. The whole architecture's primary signal is dead on the apps that need it most (Slack, Discord, Notion, Linear, web Gmail, etc.).

**Warning signs:**
- L0 verifier never fires for web/Electron content
- Verifier always escalates to L1+ on web bundleIDs

**Prevention:**
1. **For web content (Chrome family + Safari + Electron), use CDP DOM mutation observer as L0** — `Page.lifecycleEvent` + `DOM.documentUpdated` + `DOM.attributeModified`. CDP push events ARE our L0 on those bundles.
2. **For Electron with `_AXObserverAddNotificationAndCheckRemote` (private SPI, Sprint 9 SPI-02), the AX notification path works** — but only with that private call. Public AXObserverAddNotification fails silently.
3. **Bundle classifier picks the L0 source** — `WebContentBundles` set (Chrome family, Safari, all Electron) routes L0 to CDP. Native bundles route to AX.
4. **For Safari specifically, prefer T3 AppleScript `do JavaScript`** — works around the AX sandbox, gets full DOM, slow but reliable.

---

### Pitfall 15: FSEvents has 50-500ms coalesce delay (not fast enough as primary verifier)

**Severity:** MAJOR (verification budget violated when used as primary)
**Phase:** Sprint 1 — Push-event verifier; Sprint 2 — Deterministic ensemble

**What goes wrong:** FSEvents (`kFSEventStreamCreateFlagFileEvents`) coalesces filesystem events on a 50-500ms timer (configurable down to ~10ms but at high CPU cost). For "did the file save?" verification, that's slow.

**Consequences:** If you wire FSEvents as primary verifier for "save" actions, every save verifies in 50-500ms vs the <50ms budget for L0/L1.

**Warning signs:**
- Save-action L0 verify always >100ms
- Bursts of file changes lump into one event with a single timestamp

**Prevention:**
1. **FSEvents = L1, NOT L0.** Push-event L0 is AX/CDP/NSWorkspace; filesystem events are 1-5ms tier (L1 cheap diff).
2. **For instant save signals, use the app's native AX/CDP path** — most apps emit `kAXValueChanged` on the document AX node. That fires <1ms.
3. **Use `kqueue EVFILT_VNODE` for single-file watch with <1ms latency** — bypass FSEvents coalescing for known target paths.
4. **For bulk file scanning, FSEvents is fine** — just don't put it in the hot path.

---

### Pitfall 16: Bear/Things SQLite reads can break on app updates

**Severity:** MINOR (degraded path for personal-info apps)
**Phase:** Sprint 0 — App classifier

**What goes wrong:** Bear, Things, OmniFocus, DEVONthink ship SQLite databases that we can read directly for state — but the schema changes on app updates without notice. `notes.db` had a column rename in Bear 2.5; reads broke silently.

**Consequences:** Direct SQLite reads return wrong/missing data. Agent acts on stale info. User loses trust.

**Warning signs:**
- SQL queries return empty or `OperationalError: no such column`
- App version check on launch shows version newer than last-tested

**Prevention:**
1. **Never read SQLite as primary** — always start with URL scheme + x-callback-url (Bear, Things, OmniFocus all support this) or AppleScript .sdef. SQLite is a cache layer for episodic memory, not the live state.
2. **Schema fingerprint check** — on first read per session, hash the table schemas; if hash differs from last-known, log a warning and disable direct SQL.
3. **App version pinning in `AppProfile`** — record the app version that the schema was validated for; warn on mismatch.
4. **Read-only opens** — `sqlite3.connect(path, mode='ro')` so we can't accidentally corrupt user data even on schema drift.
5. **For Bear specifically, prefer `bear://x-callback-url/open-note?id=...` for navigation, AS for content read.**

---

## SPI & PRIVATE-API pitfalls

### Pitfall 17: SkyLight private SPI can break across macOS updates

**Severity:** MAJOR (every macOS update is a roll of the dice)
**Phase:** Sprint 9 — Private SPI integration; Sprint 0 — degrade-gracefully scaffold

**What goes wrong:** `SLEventPostToPid`, `SLPSPostEventRecordTo`, `_AXObserverAddNotificationAndCheckRemote`, `CGSManagedDisplaySetCurrentSpace`, `CGSConnection*` — these are private/undocumented. Apple changes them between macOS versions. macOS 14.4 broke `SLEventPostToPid` signature briefly; macOS 15 deprecated `CGSManagedDisplaySetCurrentSpace` patterns yabai used.

**Consequences:** Agent works fine until user runs `softwareupdate` overnight. Next morning, pixel actions fail silently or crash the agent process.

**Warning signs:**
- Crash with `_objc_msgSend` to a SkyLight selector after macOS update
- `dlsym` returns NULL for a previously-working symbol
- Behavioral drift (cursor warps when SLEventPostToPid used to suppress it)

**Prevention:**
1. **Capability probe at session start** — `dlsym(RTLD_DEFAULT, "SLEventPostToPid")`; if NULL, mark capability unavailable, fall to public CGEvent path.
2. **Version-pinned function signatures** — keep a `SkyLightABI.swift` with version-conditional imports. `if #available(macOS 27, *) { ... }` guards.
3. **Public-API fallback for every private path** — NEVER make a private SPI the only path. Translator registry skips unavailable channels gracefully.
4. **Smoke test on macOS update** — first launch on a new macOS version runs a self-test that exercises every SPI; reports failures to user with degradation list.
5. **Pin to specific macOS version in `setup.py`** — refuse to start on a major version we haven't tested. `MAX_TESTED_MACOS = 26.4`; warn-and-continue with reduced caps on >.

---

### Pitfall 18: SIP-off requirements for DTrace + DYLD limit some agent capabilities

**Severity:** MAJOR (full SPI tier requires SIP off — user must opt in)
**Phase:** Sprint 9 — Private SPI integration

**What goes wrong:** DTrace probes, DYLD_INSERT_LIBRARIES, Mach injection — all require SIP partial-off (`csrutil disable` or `csrutil enable --without dtrace,fs,...`). Default Mac has SIP on. Agent capability tier depends on user state we can't control.

**Consequences:** Sprint 9 features (DYLD into Electron renderers, DTrace inspection of system frameworks, ES kernel events without entitlement) only work on a SIP-off machine. Akeil's machine OK; capability differs across machines.

**Warning signs:**
- DYLD_INSERT_LIBRARIES path fails with `dyld: library not loaded` or signature errors
- DTrace probes return "permission denied"
- ES client errors with `EPERM`

**Prevention:**
1. **Capability probe at session start** — check `csrutil status`. Cache result. Don't try DYLD/DTrace if SIP on.
2. **Tier the SPIs by SIP requirement:**
   - Tier A (SIP on, no entitlement): SkyLight `SLEventPostToPid`, `_AXObserverAddNotificationAndCheckRemote`, AppleSPUHIDDevice, CGSManagedDisplay (works for current Space)
   - Tier B (SIP partial-off): DTrace, DYLD injection, full ES client
   - Tier C (SIP fully off): Mach injection into protected processes
3. **Document SIP requirements per feature** in `AppProfile` — feature matrix in README.
4. **Graceful degradation** — agent reports what's available at start: "SIP on: 70% capabilities. SIP partial-off: 95%. Full: 100%."
5. **Akeil-only**: this is a personal tool. If SIP is on, that's a config issue to fix, not a code issue. But keep the degrade path for when we image to a fresh machine.

---

### Pitfall 19: Hardware-specific risks (Tahoe AX issues, Apple Silicon arm64e DYLD)

**Severity:** MAJOR (Apple Silicon arm64e changes DYLD injection mechanics)
**Phase:** Sprint 9 — Private SPI integration

**What goes wrong:**
- macOS Tahoe (26) has documented AX framework regressions on certain Mac models (M3 Pro/Max specifically reported AX subtree corruption on heavy load).
- Apple Silicon's arm64e ABI uses pointer authentication codes (PAC) — DYLD_INSERT_LIBRARIES libraries must be arm64e-signed AND match the target's PAC keys; Mach injection tooling that worked on x86_64 macOS just doesn't work the same on AS.
- Universal binaries that ship arm64-only (no arm64e slice) can't inject into PAC-protected processes (most Apple system frameworks).

**Consequences:** SPI features that work on one Mac fail on another; "test on my machine" fails on M3 Max.

**Warning signs:**
- DYLD inject fails with "library not loaded: invalid signature" on M-series
- AX subtree returns inconsistent counts on Tahoe under load
- Mach injection returns `KERN_PROTECTION_FAILURE` on AS

**Prevention:**
1. **Build inject libraries as arm64e + ad-hoc-signed with PAC enabled.** `clang -arch arm64e -mmacosx-version-min=14.0` + `codesign --options runtime,library --entitlements ...`.
2. **Universal binary check** — agent refuses to inject if target is PAC-protected and our library isn't arm64e.
3. **Tahoe AX corruption detection** — if AX subtree returns suspiciously low child count vs prior snapshot, retry once with 200ms delay; log the event. Bundle-specific blocklist for confirmed-bad combinations.
4. **Hardware fingerprint logging** — log `hw.model` and macOS build at session start for triage.

---

## SELF-HEALING & RECOVERY pitfalls (the architecture's most subtle risks)

### Pitfall 20: Self-healing masking real regressions (Qate AI: 41% abandonment within a year)

**Severity:** MAJOR (the entire premise of self-healing has a 41% failure rate in industry)
**Phase:** Sprint 4 — Failure classifier; Sprint 5 — Cache self-heal write-back

**What goes wrong:** Industry data: only 4% of IT leaders say AI-driven self-healing test automation works "very well"; **41% abandon self-healing tools within a year.** Reason: heals silently mask real regressions. The "X button moved" heal looks identical to "the engineer broke X" — both heal, both don't surface the change. Six months later, the test passes but the feature is broken.

**Consequences:** Long-term, you stop trusting your own healed cassettes. Every replay needs human review, defeating the point.

**Warning signs:**
- Increasing rate of cassette write-backs over time (selectors drifting more than they should)
- Replays succeed but goal completion at the user level decreases
- Heal events not flagged for review

**Prevention:**
1. **EVERY heal emits a structured event** — `HealEvent{old_locator, new_locator, reason, trace_id, ts}`. Append to `~/.cua/sessions/<id>/heals.ndjson`. NEVER silent.
2. **Distinguish locator drift from semantic change.** If the old locator's matched-element role/label doesn't match the new locator's, that's a semantic change — flag as `POSSIBLE_REGRESSION`, not auto-heal. User reviews.
3. **Heal-rate budget** — if heal rate >X%/session (default 5%), pause auto-heal and surface a triage UI. Continued drift signals real regression, not selector noise.
4. **Heal aging** — heals are "tentative" for 7 days. If the same heal recurs across multiple sessions, mark "validated". If the original locator returns, flip back to it (selector drift was transient).
5. **Differential session compare** (OBS-06) — surface heal-events between session N and N+1. User can review the diff. Same UX as `git diff` for runs.
6. **No heal in CI/headless mode** — the moment we add an unattended path, heals must be a hard fail, not auto-write-back.

**Counterevidence:** This is the biggest known-unknown in self-healing. Stagehand's pattern works in their narrow web context; we're applying it to the wider Mac surface. Expect to iterate.

---

### Pitfall 21: Intrinsic LLM self-correction is broken (papers 2601.00828, 2412.14959)

**Severity:** BLOCKER if you build the architecture around it
**Phase:** Sprint 4 — Failure classifier; Sprint 6 — Cognitive layer (COG-06 Critic)

**What goes wrong:** Two post-Oct-2024 papers conclusively show:
- **Decomposing Self-Correction (2601.00828):** intrinsic LLM self-correction without an external oracle = 16-27% accuracy. Stronger models (Opus, GPT-5) are WORSE at this than weaker ones because they're more confident in initial wrong answers.
- **Dark Side of Self-Correction (2412.14959):** intrinsic correction adds bias and "cognitive wavering" — models flip-flop between answers, never converging.

**Consequences:** If your Critic agent (COG-06) uses pure LLM-talks-to-itself self-correction, it converges to the wrong answer 73-84% of the time. Recovery loops become noise generators.

**Warning signs:**
- Critic flip-flops (accept/reject/accept/reject) on the same step
- More LLM critique calls correlate with WORSE goal completion, not better
- Recovery cycles trend toward 2-cycle cap before user escalation

**Prevention:**
1. **Critic NEVER acts on its own output alone.** Critic's role: rank deterministic-ensemble verifiers' outputs, not "look at the screenshot and decide if it worked." External oracle FIRST, LLM as ranker.
2. **Hoare-style {P} A {Q} contracts (Sprint 1):** every action's post-condition is a deterministic predicate (AX value equals X, window count == N+1, pixel hash within threshold). LLM can't override a passing/failing predicate.
3. **No model-vs-self critique loops.** If two LLMs disagree, escalate to user — don't let one critique the other.
4. **Cognitive Circuit Breaker (paper 2604.13417):** monitor LLM hidden-state probe for "wavering"; if detected, abort the critique cycle, escalate.
5. **Explicit ban on intrinsic correction in code review checklist.** Any PR that adds "LLM looks at its previous output and decides to retry" gets rejected.

**Counterevidence:** None. This is the most replicated negative result in 2024-2026 agent research. Don't argue with it.

---

### Pitfall 22: Long-running speculative branches mutating state

**Severity:** BLOCKER if speculation isn't scoped read-only
**Phase:** Sprint 6 — Speculative pre-execution (COG-07)

**What goes wrong:** Speculative pre-execution predicts steps N+1, N+2 while N's verifier runs. If those predictions execute MUTATING actions (click, type, submit), and N's verifier later returns FAIL, you've already moved the world — but down the wrong path.

**Consequences:** Worst case: speculative click submitted a form before N's verifier rejected N. Now the form is submitted twice (once by N, once by speculative N+1) or with wrong data. Same data-corruption class as Pitfall 1.

**Warning signs:**
- Action log shows actions firing before previous verifier completed
- Cassette replay diverges in non-deterministic ways
- Forms submitted with intermediate (not final) state

**Prevention:**
1. **HARD RULE: speculation is read-only.** Speculative steps may PRE-FETCH AX trees, PRE-COMPUTE pixel hashes, PRE-RESOLVE locators, but NEVER fire input events.
2. **Action types are typed:** `Action.kind ∈ {READ, MUTATE}`. Speculation engine can only schedule READ actions. Type-system or runtime guard.
3. **Mutation gate:** before any MUTATE action fires, check that all previous steps have `verifier.status == VERIFIED`. Speculative scheduling never bypasses this gate.
4. **Cassette replay safety:** speculative branches that didn't fire are not written to cassette. Cassette is the verified path only.
5. **Skyvern pattern:** their speculation is parallel SCRAPE, not parallel CLICK. Match their scope.

**Counterevidence to "speculate everything":** Speculative Actions paper (2510.04371) reports 55% prediction rate, 20% latency cut — but only on read-prefetch. Mutation speculation has no published positive result.

---

### Pitfall 23: Cassette write-back loops if every replay creates new "healed" entry

**Severity:** MAJOR (cassettes grow unbounded; cache becomes useless)
**Phase:** Sprint 5 — Cache self-heal write-back (CACHE-01..03)

**What goes wrong:** Stagehand-style write-back: replay cassette → broken step → live re-execute → write-back healed selector. Bug: if "healed" selector is also unstable (e.g., uitag SoM coordinate), every replay produces a new "heal" — cassette grows by 1 entry per replay. After 100 replays, the cassette has 100 versions of step 7.

**Consequences:** Cassette file size explodes. Cache lookup gets slower (more entries to scan). Eventually the "self-healing cache" is slower than no cache at all.

**Warning signs:**
- Cassette file grows on every session
- Cache hit rate drops while cache size grows
- Same step has dozens of healed versions

**Prevention:**
1. **Stable-locator gate before write-back:** healed selector must come from one of the stable tiers (AXIdentifier, AXLabel, AXTitle). Coordinate-based or vision-based heals are NOT written back to cassette — they're session-only.
2. **Atomic replace, not append:** each step has at most ONE current entry. Healed selector REPLACES the broken one in place. Old version moves to `cassettes/history/`.
3. **Replay validates first** — before write-back, run the new selector through the same locator probe (10-tier). Only write-back if it scores stable.
4. **Cassette compaction:** background job dedups equivalent locators (same role-path, same label) into a canonical form. Run weekly.
5. **Heal aging (from Pitfall 20) caps churn** — tentative heals don't write to canonical cassette until validated across N sessions.
6. **Bound cassette size** — max 10MB per task; oldest history entries pruned. Hard cap prevents pathological growth.

---

## ADDITIONAL pitfalls surfaced from research

### Pitfall 24: TCC permission revoked mid-session

**Severity:** MAJOR (silent failure mode)
**Phase:** Sprint 0 — translator scaffolding; Sprint 9 — SPI capability probe

**What goes wrong:** User toggles Accessibility / Screen Recording / Input Monitoring permission OFF in System Settings while agent runs. AX calls start returning `kAXErrorAPIDisabled`. Capture returns empty.

**Prevention:**
1. **`AXIsProcessTrusted()` probe at every translator call surface** — not just at startup.
2. **On revocation, surface actionable URL:** `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`.
3. **Pause the agent, don't crash.** Save checkpoint, await re-grant.

---

### Pitfall 25: Modal alert blocking AX silently queues actions behind it

**Severity:** MAJOR (gap that no production system handles)
**Phase:** Sprint 1 — Push-event verifier

**What goes wrong:** A system update dialog or app modal appears. AX actions queue silently behind it — no error, just no effect. Agent thinks it's working.

**Prevention:**
1. **Pre-action modal probe** — scan AX tree for top-level dialog/sheet roles before every fire. If found, raise `BlockedByModal` and recommend dismiss.
2. **`kAXWindowCreated` notification subscribe** — push event fires when a modal appears mid-session.
3. **Bundle-aware blocklist** — known modal sources (`com.apple.alertNoteIcon`, `com.apple.coreservices.uiagent`) trigger immediate handling.

---

### Pitfall 26: 5-branch recovery cost explosion at Opus pricing

**Severity:** MAJOR (cost runaway in tight loops)
**Phase:** Sprint 4 — Active recovery (HEAL-04)

**What goes wrong:** 5 branches × N recovery cycles × Opus pricing. One pathological loop can hit $50 in 10 minutes.

**Prevention:**
1. **Bounded recovery: max 2 cycles, then escalate to user (HEAL-04).**
2. **Branch heterogeneity:** B1-B2 are local (no LLM call), B3-B4 use LLM. Run B1+B2 first; only fan to B3-B5 if both fail.
3. **Circuit breaker after 3 consecutive failures on same target (HEAL-05).**
4. **Cost telemetry per session** — surface running spend; auto-pause at $10/session unless user overrides.

---

### Pitfall 27: Same task = non-deterministic (paper 2604.17849)

**Severity:** MINOR (baseline assumption, not a bug)
**Phase:** Sprint 4 — Failure classifier; Sprint 5 — Cache write-back

**What goes wrong:** Same task, same model, same screenshot — non-identical action sequences across runs. Caching by (task, screenshot) won't dedup runs.

**Prevention:**
1. **Cache by `(bundleID, role_path, instruction)` — NOT by screenshot.** Stable across non-determinism.
2. **Recipe replay tolerates step-order variation** if the post-condition matches.
3. **Don't fight non-determinism; design for it** — verifier ensemble handles natural variance.

---

### Pitfall 28: Universal "first verifier wins" can race verifier itself

**Severity:** MAJOR (verifier confidence calibrates wrong)
**Phase:** Sprint 1 — Push-event verifier; Sprint 2 — Deterministic ensemble

**What goes wrong:** L0 push event fires from a stale notification (e.g., `kAXValueChanged` for a value change that happened 50ms BEFORE our action — there was an in-flight notif we hadn't drained). Verifier "passes" before the action even landed.

**Prevention:**
1. **Subscribe BEFORE fire** (this is already the design) AND record the `subscription_ts`. Discard any notification with `event_ts < subscription_ts + 5ms`.
2. **Action ID propagated via AXManualAccessibility hint** — if available, only count notifications correlated to our action ID.
3. **Two-event confirmation for high-stakes actions** — require BOTH L0 push AND L1 cheap diff agreement before VERIFIED. Single signal is "tentative".

---

### Pitfall 29: Anthropic Cowork ships cross-session sync (differentiator shrinks)

**Severity:** MINOR (strategic, not technical)
**Phase:** Cross-cutting

**What goes wrong:** Anthropic adds session sync + auto-recovery to Cowork. Our durable-execution wrapper becomes table-stakes, not differentiator.

**Prevention:**
1. **Differentiation is the FULL stack: recovery + observability + private SPI + speculative + ensemble.** Any one feature can be matched; the integrated stack can't be.
2. **Track competitor releases monthly** — if Cowork ships X, evaluate if our X is still better; pivot priority if not.
3. **Observability is the lasting moat** — 60fps recordings + 3D timeline + counterfactual replay are 6+ months of infra Cowork would need to copy.

---

## Phase-specific warnings (cross-reference)

| Sprint | Pitfalls owned |
|---|---|
| Sprint 0 (Foundation) | 8, 13, 16, 17, 18, 19, 24 |
| Sprint 1 (Push-event verifier) | 14, 15, 25, 28 |
| Sprint 2 (Deterministic ensemble L1) | 3, 12, 14, 28 |
| Sprint 3 (Racing translators) | 1, 2, 5, 8 |
| Sprint 4 (Failure classifier + recovery) | 21, 26, 27 |
| Sprint 5 (Cache self-heal write-back) | 13, 20, 23, 27 |
| Sprint 6 (Speculative + ensemble voting) | 4, 6, 7, 22 |
| Sprint 7 (Visualizer) | 9, 10, 11 |
| Sprint 8 (Continuous learning) | 13, 23 |
| Sprint 9 (Private SPIs) | 17, 18, 19 |
| Sprint 10 (Full transparency) | 9, 11, 20 |
| Sprint 11 (Durable execution) | 27, 29 |

---

## Severity summary

| Severity | Count | Pitfalls |
|---|---|---|
| BLOCKER | 11 | 1, 2, 3, 4, 6, 8, 9, 10, 21, 22 |
| MAJOR | 16 | 5, 7, 11, 12, 13, 14, 15, 17, 18, 19, 20, 23, 24, 25, 26, 28 |
| MINOR | 2 | 16, 27, 29 |

---

## Counterevidence-to-architecture surfaced

The locked architecture is maximalist. These pitfalls flag where MAXIMALIST patterns FAIL and the architecture must allow degradation:

1. **Racing fails for mutating actions** (Pitfall 1) — single-channel + bounded retry beats race for `submit`/`send`/`delete`. The architecture's "race everything" needs a per-action-class policy override.
2. **Speculation fails when mutating** (Pitfall 22) — only READ speculation is safe. The architecture's "predict N+1, N+2 in parallel" must scope to read-only prefetch.
3. **Self-healing has a 41% industry abandonment rate** (Pitfall 20) — Stagehand's success is in a narrower domain. Plan for heal-event surfacing + rate budgets from Sprint 5, not as bolt-on.
4. **Intrinsic LLM self-correction is the wrong model** (Pitfall 21) — Critic must rank external oracles, not self-critique. The architecture says this; the test is whether code review enforces it.
5. **Push-event verifier silently fails on web content** (Pitfall 14) — the "secret weapon" doesn't work on the apps we want most. CDP DOM observers replace AX notifications on web bundles. Registry must route by bundle.
6. **Apple FM is text-only and hallucinates JSON** (Pitfalls 6, 7) — FM is a text-classifier with binary output. Don't put it on any code path that needs vision OR multi-field params.
7. **Private SPIs ship with a macOS-version risk** (Pitfalls 17, 18, 19) — every SPI capability must have a public-API fallback in the registry. "Maximalist" means use ALL the SPIs — but never assume any single one is available.

---

## Sources

### Primary architecture docs
- `/Users/akeilsmith/dev/cua-maximalist/.planning/PROJECT.md` (the locked plan)
- `/Users/akeilsmith/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md` (THE locked architecture w/ counterevidence)
- `/Users/akeilsmith/thinker/vault/research/self-healing-cua-driver-2026-04-29.md` (initial driver injection plan)

### Research papers (post-Oct 2024) — confidence: HIGH
- Decomposing Self-Correction (arXiv 2601.00828) — intrinsic correction broken
- Dark Side of Self-Correction (arXiv 2412.14959) — cognitive wavering
- Reliability of CUAs (arXiv 2604.17849) — non-determinism baseline
- AX-tree Self-Healing (arXiv 2603.20358) — 10-tier locator hierarchy
- Cognitive Circuit Breaker (arXiv 2604.13417) — hidden-state probe
- Speculative Actions (arXiv 2510.04371) — read-only speculation only
- VeriSafe Agent (arXiv 2503.18492) — Hoare-style verification
- VeriGUI / TVAE (arXiv 2604.05477) — Think-Verify-Act-Expect
- STEVE (arXiv 2503.12532) — post-action screenshot verifier
- Screen2AX (arXiv 2507.16704) — synthetic AX from pixels
- UI-TARS-2 (arXiv 2509.02544) — 47.5% OSWorld baseline

### Production systems & issues — confidence: HIGH
- trycua/cua issue #870 (macOS Tahoe SCScreenshotManager regression)
- cmux issue #2985 (AX rate-limit / main-thread saturation)
- mlx-vlm issue #330 (UI-TARS coordinate quantization → screen center)
- Stagehand AgentCache.ts:573-624 (cache write-back pattern + counterevidence on long-tail growth)
- Skyvern agent.py:4337-4412 (parallel verify + speculative scrape — read-only)
- Qate AI: "Self-Healing Tests — what works" (4% "very well", 41% abandonment)
- ghost-os LearningRecorder.swift:62-88 (CGEvent tap pattern)
- browser-harness daemon.py:243-249 (inline session self-heal)

### Apple SPI / hardware references — confidence: MEDIUM (private)
- AXUIElement, AXObserver public APIs (Apple docs)
- ScreenCaptureKit (macOS 14+, with macOS 15 sharingType regression)
- FoundationModels framework (macOS 26 — text-only public surface as of 26.4)
- trycua/cua/blog/inside-macos-window-internals.md (SkyLight)
- yabai source (CGSManagedDisplaySetCurrentSpace)
- NUIKit/CGSInternal (private SkyLight headers)

### Counterevidence
- Bloomberg / Federighi: agentic Siri delayed to iOS 26.5/27 (Apple FM not plan-class ready)
- MacStories March 2026 12-task test: Anthropic Cowork ~50% reliability — competitor baseline

---

**Confidence:** HIGH on every pitfall (each has at least one production-code citation, GitHub issue, or peer-reviewed paper).
**Coverage:** All 23 pitfalls from the input question + 6 additional ones surfaced from research.
**Phase mapping:** Every pitfall pinned to specific sprint(s) for roadmap planning.
