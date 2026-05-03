# basicCtrl

**Let an AI assistant actually use your Mac apps for you — Slack, Cursor, Chrome, Calendar, anything.**

```
You: "Send a message to #general saying I'm running 5 minutes late"
                            ↓
              ┌─────────────────────────────┐
              │  basicCtrl picks the right  │
              │  way to drive Slack,        │
              │  clicks, types, verifies    │
              │  the message went through   │
              └─────────────────────────────┘
                            ↓
You: ✅ done — and it remembers how, so next time it's instant
```

Local-only. No cloud. macOS 26 (Tahoe) on Apple Silicon. Single user.

---

## What it actually does (for non-technical readers)

Think of basicCtrl as a "remote control" your AI assistant uses to drive your Mac.

It can:
- **Send messages in Slack, Discord, or Linear** — picks the right channel, types, sends, confirms it worked.
- **Drive Cursor or VS Code** — open files, run commands, paste code into the AI sidebar.
- **Use your real Chrome** — with your logins and cookies. Can fill forms, click buttons, scrape data, take screenshots.
- **Quick-add events to Calendar** with natural-language ("Lunch with Sam tomorrow at 1pm").
- **Send mail, edit Notes, type into TextEdit, run Terminal commands** — every Mac app it knows how to talk to.
- **Learn from each successful run** — second time you ask, it skips the figuring-out part and just does it.
- **Catch its own mistakes** — if a click fails, it tries five different recovery strategies before giving up.

Why "self-healing": software changes. Buttons move. Pages restructure. basicCtrl notices when something failed and tries other ways to do the same thing — instead of silently breaking like most automation tools.

---

## Three ways it talks to apps

basicCtrl picks the fastest, most reliable route for each app. You don't have to think about it — but here's the picture:

```
┌──────────────────┬──────────────────────┬─────────────────────────┐
│  BUCKET          │  USED FOR            │  HOW IT WORKS           │
├──────────────────┼──────────────────────┼─────────────────────────┤
│  AX              │  Native Mac apps     │  Apple's accessibility  │
│  (default)       │  (Calendar, Mail,    │  framework — same thing │
│                  │   Notes, Finder…)    │  VoiceOver uses         │
├──────────────────┼──────────────────────┼─────────────────────────┤
│  Browser         │  Your real Chrome    │  Connects to Chrome's   │
│                  │  with your logins    │  built-in remote-debug  │
│                  │  (also Brave, Edge,  │  port. Sees the live    │
│                  │  Arc)                │  page, not a copy.      │
├──────────────────┼──────────────────────┼─────────────────────────┤
│  Electron        │  Slack, Discord,     │  Same trick as Browser  │
│                  │  Cursor, VS Code,    │  — Electron apps ARE    │
│                  │  Linear, Figma,      │  Chrome inside. Per-app │
│                  │  Notion, Spotify,    │  launch flag opens a    │
│                  │  Obsidian, more      │  remote-control port.   │
└──────────────────┴──────────────────────┴─────────────────────────┘
```

**Why three buckets:** each kind of app responds to a different language. Trying to use one approach for everything makes things slow and fragile. Picking the right one for each gets you 5–10× faster, more reliable automation.

**A few things sit outside the three buckets:**

- **Terminal panes (Ghostty, iTerm2, Terminal, Alacritty, Warp).** AX *does not work* — terminals draw text to a framebuffer, not into AXTextArea cells. Even if AX inserts succeed, text lands in the wrong tab or vanishes (per `basicctrl/skills/com.mitchellh.ghostty/claude-code-tabs.md:36-46`). The framework uses **osascript + System Events keystroke** instead — that posts HID events the terminal interprets through the PTY. Different pipeline from AX.
- **Safari.** No CDP. Uses **AppleScript "do JavaScript" bridge** via the `page` tool.
- **Games / Flutter / OpenGL canvases.** No AX, no DOM. Uses **Vision OCR + pixel HID click** as L4/L5 fallback within the healing tools.

---

## Install

```bash
git clone https://github.com/akeildev/basicCtrl.git
cd basicCtrl
uv sync                          # creates .venv from uv.lock
uv pip install -e .              # installs the basicctrl package
```

**Optional — durable runs (Postgres).** Only needed if you want the framework to survive a crash mid-task and pick up where it left off. The MCP server starts fine without it (`main.py:146` logs `durable.setup_failed_continuing_without_postgres` and continues). Skip unless you specifically want this.

```bash
brew install postgresql@16
brew services start postgresql@16
bash scripts/init_postgres.sh    # provisions the basicctrl DB
```

---

## Wire it into Claude Code (or any MCP host)

Add to `~/.claude.json` (or your MCP host's config):

```json
{
  "mcpServers": {
    "basicCtrl": {
      "command": "uv",
      "args": ["run", "python", "-m", "basicctrl.mcp_server"],
      "cwd": "/absolute/path/to/basicCtrl"
    }
  }
}
```

Restart your MCP host. The tool surface appears as `mcp__basicCtrl__*`.

---

## One-time Chrome setup (browser bucket only)

For browser automation against your real Chrome profile (with your cookies + extensions), Chrome needs remote-debugging enabled — per-profile sticky:

1. In your Chrome, navigate to `chrome://inspect/#remote-debugging`.
2. Tick "Allow remote debugging for this browser instance".
3. On Chrome 144+, click "Allow" on the in-browser popup that appears the first time the daemon attaches.

After that, browser automation auto-discovers the connection. No relaunch flags. No re-ticking.

---

## First example

Once basicCtrl is wired up, ask your AI assistant something like:

> "Open my Calendar and add an event called 'Dentist' for Friday at 3pm"

The framework will:
1. Recognize Calendar.app → AX bucket
2. Bring Calendar to the front
3. Use the quick-add (`cmd+n`) shortcut
4. Type the event with natural-language parsing
5. Verify it shows up in the right day
6. Save the recipe so the next "add an event" is instant

Or:

> "Send a message in my #engineering Slack saying I'll be late"

1. Recognize Slack → Electron bucket
2. Check if Slack is running with debugging on; if not, ask "OK to relaunch Slack?" (so you don't lose drafts)
3. Connect via CDP, find #engineering
4. Type message, click Send
5. Verify the message appears (strict-verify, not "probably worked")

---

## Architecture (technical)

```text
┌────────────────────────────────────────────────────────────────────────┐
│  MCP host (Claude Code, Codex, etc.)                                    │
└──────────────────────────┬─────────────────────────────────────────────┘
                           │ JSON-RPC over stdio
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│  basicctrl/mcp_server/  ─  proxy + healing_tools + browser_tool +       │
│                            electron_tool                                │
│   - 8 healing tools wrap RaceOrchestrator + RecoveryOrchestrator       │
│   - 1 browser tool   (mcp__basicCtrl__browser)                         │
│   - 1 electron tool  (mcp__basicCtrl__electron)  ← three-bucket router │
└──────────┬────────────────────────────┬─────────────────────────────┬──┘
           │                            │                             │
           ▼                            ▼                             ▼
┌──────────────────────────┐ ┌────────────────────┐ ┌─────────────────────┐
│  AX bucket               │ │  Browser bucket    │ │  Electron bucket    │
│   RaceOrchestrator       │ │   CDP daemon →     │ │   per-app daemon →  │
│   races T1+T2+T3+T4+T5   │ │   user's Chrome    │ │   launches app w/   │
│   in parallel            │ │   via DevTools     │ │   --remote-debug    │
│                          │ │   ActivePort       │ │   -port=NNNN        │
│   RecoveryOrchestrator   │ │                    │ │                     │
│   B1 rescroll            │ │   Self-heal:       │ │   Self-heal L1-L5:  │
│   B2 OCR-reground        │ │   stale WS,        │ │   retry, auto-      │
│   B3 world-replan        │ │   omnibox-popup,   │ │   launch, port-     │
│   B4 planner-replan      │ │   setup-needed     │ │   collision, stale  │
│   B5 AppleScript         │ │                    │ │   WS                │
└──────────────────────────┘ └────────────────────┘ └─────────────────────┘
```

---

## Tools (MCP surface)

| Tool                                       | Bucket    | Purpose                                                              |
| ------------------------------------------ | --------- | -------------------------------------------------------------------- |
| `mcp__basicCtrl__click_with_healing`       | AX        | Click a labeled element; races T1+T2+T3+T4+T5; auto-recovers B1-B5   |
| `mcp__basicCtrl__type_with_healing`        | AX        | Type into a focused or labeled field                                 |
| `mcp__basicCtrl__key_combo_with_healing`   | AX        | Hotkey (cmd+n, return, etc.); destructive verbs forced single-channel |
| `mcp__basicCtrl__scroll_with_healing`      | AX        | Scroll a region with healing                                         |
| `mcp__basicCtrl__set_value_with_healing`   | AX        | Set a labeled element's value                                        |
| `mcp__basicCtrl__send_destructive`         | AX        | Submit / send / delete; never raced (D-11 safety)                    |
| `mcp__basicCtrl__register_task_complete`   | meta      | Flush observed actions → Recipe → FAISS                              |
| `mcp__basicCtrl__do_task`                  | meta      | Autonomous: ask host LLM for plan + execute                          |
| `mcp__basicCtrl__browser`                  | Browser   | CDP ops on user's Chrome — navigate, js, query_dom, click_xy, fill, screenshot |
| `mcp__basicCtrl__electron`                 | Electron  | Drive Slack / Cursor / Discord / VS Code / Linear / etc. via per-app CDP |
| 29 cua-driver primitives                   | AX (raw)  | launch_app, list_windows, get_window_state, click, type_text, drag, hotkey, screenshot, page (AS bridge), check_permissions, etc. |

---

## Routing rules — which bucket gets the call

```
APP CLASS                              BUCKET                  TOOL
────────────────────────────────────   ────────────────────    ─────────────────────────
Chromium browser                       Browser                 mcp__basicCtrl__browser
(Chrome, Brave, Edge, Arc, Opera)      (user's running         (auto-discovers via
                                        Chrome)                 DevToolsActivePort)

Electron app                           Electron                mcp__basicCtrl__electron
(Slack, Cursor, Discord, VS Code,      (per-app daemon,        (pass bundle_id)
 Linear, Figma, Notion, Spotify,        auto-launch w/ flag)
 Obsidian, Teams, Signal, Postman,
 GitHub Desktop, Todoist, more)

Native Cocoa                           AX                      *_with_healing tools
(Finder, Calendar, Mail, Notes,                                (race T1+T2+T3+T4+T5)
 TextEdit, Calculator, Pages…)

Safari                                 AppleScript JS bridge   page tool (osascript
                                       (no CDP equivalent)     "do JavaScript")

Terminal emulator                      Keystroke via System    osascript keystroke
(Ghostty, iTerm2, Terminal,            Events (HID → PTY).     (DO NOT use AX —
 Alacritty, Warp)                      Separate pipeline       AX text insert lands
                                       from AX entirely.       in wrong tab / nowhere.
                                                               See com.mitchellh.ghostty/
                                                               claude-code-tabs.md)

Game / OpenGL canvas / Flutter         Vision OCR + pixel      L4 Vision OCR + L5 pixel
                                       HID click (no AX,       click via CGEvent.
                                       no DOM available)       Lives as fallback inside
                                                               the *_with_healing tools.
```

---

## Per-app skills

Pre-tested recipes live in `basicctrl/skills/<bundle_id>/<topic>.md`. The MCP server reads these into planner prompts so multi-step flows on a known app skip rediscovery.

| App              | Bundle ID                          | Bucket    | Skill                        |
| ---------------- | ---------------------------------- | --------- | ---------------------------- |
| Calendar         | `com.apple.iCal`                   | AX        | `quickadd.md`                |
| Calculator       | `com.apple.calculator`             | AX        | `arithmetic.md`              |
| Mail             | `com.apple.mail`                   | AX        | `messaging.md`               |
| Notes            | `com.apple.Notes`                  | AX        | `notes.md`                   |
| Safari           | `com.apple.Safari`                 | AX/page   | `general.md`                 |
| TextEdit         | `com.apple.TextEdit`               | AX        | `typing.md`                  |
| Chrome           | `com.google.Chrome`                | Browser   | `general.md`                 |
| Slack            | `com.tinyspeck.slackmacgap`        | Electron  | `messaging.md`               |
| Cursor           | `com.todesktop.230313mzl4w4u92`    | Electron  | `cursor-cdp.md`              |
| Ghostty          | `com.mitchellh.ghostty`            | Terminal  | `claude-code-tabs.md`        |

Plus 11 more Electron apps known by `mcp__basicCtrl__electron` registry without per-app skills yet (Discord, VS Code, Linear, Figma, Notion, Spotify, Obsidian, Teams, Signal, Postman, GitHub Desktop, Todoist).

---

## Self-healing layers

Each bucket has its own recovery ladder:

**AX bucket (B1–B5 + per-tool wrappers)**
- B1 rescroll: element scrolled out of view → scroll into view, retry
- B2 OCR-reground: AX label changed → re-find by visual OCR + retry
- B3 world-replan: app state diverged from plan → take screenshot, re-plan from current state
- B4 planner-replan: full task replan via LLM
- B5 AppleScript fallback: AX broke entirely, try AS bridge

**Browser bucket**
- Stale-WS: daemon WebSocket died → restart daemon, retry once
- Omnibox-popup: attached to internal tab → switch to real user tab
- Setup-needed: chrome://inspect not ticked → walk user through one-time setup

**Electron bucket (L1–L5)**
- L1 connect retry with backoff (port not yet bound after launch)
- L2 auto-launch with `--remote-debugging-port=NNNN` if app not running
- L3 already-running-without-CDP → clean error + needs_user_action (no silent quit)
- L4 stale WS mid-session → drop session, daemon respawns, retry once
- L5 port collision → hops to next free port in 9240–9299

---

## Hard rules (never break)

- Never run a full recursive AX tree walk (15-20s on Safari). Always depth-limited (≤3 levels).
- Never poll AX at >20 calls/sec/pid (cmux #2985 stalls Cocoa main thread).
- Always subscribe `AXObserver` push notifications BEFORE the action fires.
- Always use deterministic ensemble first (L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30.
- Destructive actions (submit/send/delete) — single-channel only, never raced.
- Always strict-verify after every submit-class action (title diff + CTA absence + explicit confirmation phrase). See AGENTS.md.
- For Electron apps, never silently quit a user's running session to enable CDP — always ask first (data loss risk on Slack drafts, Cursor unsaved files).

---

## Credits

The browser CDP daemon is vendored and namespaced from [browser-use/browser-harness](https://github.com/browser-use/browser-harness) (BSD-licensed). The cua-driver Swift sidecar comes from [trycua/cua](https://github.com/trycua/cua). Recovery patterns + race orchestration + Electron three-bucket routing are original to this repo.

## License

See `LICENSE`.
