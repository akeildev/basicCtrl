# basicCtrl

Self-healing autonomous Mac computer-use framework. Drive any macOS app — native Cocoa, browser, Electron, terminal, game — by automatically picking the right protocol per app, racing multiple action channels in parallel, verifying with deterministic ensembles before falling back to LLMs, and recovering from any failure via 5-branch parallel recovery.

> macOS 26 (Tahoe) + Apple Silicon. Local-only. Single-user. Maximum power, full transparency.

## What it does

- **Drives macOS apps** via accessibility (T1), Chrome DevTools Protocol (T2), AppleScript (T3), Vision OCR (T4), or pixel synthesis (T5) — picks the optimal channel per target, races them when latency matters, falls back when one fails.
- **Drives browsers** through a vendored CDP daemon (`basicctrl/browser/`, ported from `browser-use/browser-harness`) that walks every Chromium-class profile dir for `DevToolsActivePort`. Works against the user's everyday Chrome with their cookies, no fresh-profile relaunch.
- **Self-heals** every action through five recovery branches (B1 rescroll, B2 OCR-reground, B3 world-replan, B4 planner-replan, B5 AppleScript fallback) plus per-tool wrappers for stale-WS, missing-setup, and invisible-tab traps.
- **Learns** successful action sequences as Recipes indexed in FAISS (D-20). Second run of the same task on the same app short-circuits the planner and replays the recipe directly.
- **Verifies before declaring success.** Strict before/after diffing (title flip, CTA disappearance, explicit confirmation phrase) on every submit-class action — no silent false positives.

## Install

```bash
git clone https://github.com/akeildev/basicCtrl.git
cd basicCtrl
uv sync                          # creates .venv from uv.lock
uv pip install -e .              # installs the basicctrl package
brew install postgresql@16       # for LangGraph PostgresSaver durability
brew services start postgresql@16
```

### Wire it into Claude Code (or any MCP host)

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

Restart your MCP host. The tool surface appears as `mcp__basicCtrl__*` (one click/type/scroll/etc. per healing tool, plus `browser` for CDP-driven web work).

### One-time Chrome enablement (auto-detected, but manual setup is one click)

For browser automation against your real Chrome profile (with your cookies + extensions), Chromium needs remote-debugging enabled — per-profile sticky:

1. In your Chrome, navigate to `chrome://inspect/#remote-debugging`.
2. Tick "Allow remote debugging for this browser instance".
3. On Chrome 144+, click "Allow" on the in-browser popup that appears the first time the daemon attaches.

After that, `mcp__basicCtrl__browser` auto-discovers the WebSocket via `DevToolsActivePort` on every future launch. No relaunch flags. No re-ticking.

## Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│  MCP host (Claude Code, Codex, etc.)                                    │
└──────────────────────────┬─────────────────────────────────────────────┘
                           │ JSON-RPC over stdio
                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│  basicctrl/mcp_server/  ─  proxy + healing_tools + browser_tool         │
│   - 8 healing tools wrap RaceOrchestrator + RecoveryOrchestrator        │
│   - 1 browser tool wraps the vendored CDP daemon                        │
└──────────┬────────────────────────────────────────┬───────────────────┘
           │                                         │
           ▼                                         ▼
┌──────────────────────────────┐         ┌────────────────────────────┐
│  RaceOrchestrator             │         │  basicctrl/browser/        │
│   races T1+T2+T3+T4+T5 in     │         │   vendored CDP daemon       │
│   parallel; first verifier    │         │   (browser-harness pattern) │
│   wins                        │         │                             │
│                               │         │   - walks profile dirs for  │
│  RecoveryOrchestrator         │         │     DevToolsActivePort       │
│   B1 rescroll                 │         │   - holds persistent WS     │
│   B2 OCR-reground             │         │   - self-heal (stale WS,    │
│   B3 world-replan             │         │     omnibox-popup tab,      │
│   B4 planner-replan           │         │     setup-needed)           │
│   B5 AppleScript fallback     │         │                             │
└──────────────────────────────┘         └────────────────────────────┘
```

## Tools (MCP surface)

| Tool                          | Purpose                                                                    |
| ----------------------------- | -------------------------------------------------------------------------- |
| `mcp__basicCtrl__click_with_healing` | Click a labeled element; races T1+T2+T3+T4+T5; auto-recovers via B1-B5 |
| `mcp__basicCtrl__type_with_healing`  | Type into a focused or labeled field                                |
| `mcp__basicCtrl__key_combo_with_healing` | Hotkey (cmd+n, return, etc.); destructive verbs forced single-channel |
| `mcp__basicCtrl__scroll_with_healing` | Scroll a region with healing                                          |
| `mcp__basicCtrl__set_value_with_healing` | Set a labeled element's value                                      |
| `mcp__basicCtrl__send_destructive`  | Submit / send / delete; never raced (D-11 safety)                     |
| `mcp__basicCtrl__register_task_complete` | Flush observed actions → Recipe → FAISS                          |
| `mcp__basicCtrl__do_task`           | Autonomous: ask host LLM for plan + execute                          |
| `mcp__basicCtrl__browser`           | CDP-driven browser ops: navigate, js, query_dom, click_xy, fill, screenshot |
| 29 cua-driver primitives            | Mirrored upstream: launch_app, list_windows, get_window_state, click, type_text, drag, hotkey, screenshot, page (AS bridge), check_permissions, etc. |

## Per-app skills

Pre-tested recipes live in `basicctrl/skills/<bundle_id>/<topic>.md`. The MCP server reads these into planner prompts so multi-step flows on a known app skip rediscovery.

| App              | Bundle ID                          | Skill                        |
| ---------------- | ---------------------------------- | ---------------------------- |
| Calendar         | `com.apple.iCal`                   | `quickadd.md`                |
| Calculator       | `com.apple.calculator`             | `arithmetic.md`              |
| Mail             | `com.apple.mail`                   | `messaging.md`               |
| Notes            | `com.apple.Notes`                  | `notes.md`                   |
| Safari           | `com.apple.Safari`                 | `general.md`                 |
| TextEdit         | `com.apple.TextEdit`               | `typing.md`                  |
| Chrome           | `com.google.Chrome`                | `general.md` (CDP path A/B)  |
| Slack            | `com.tinyspeck.slackmacgap`        | `messaging.md`               |
| Cursor           | `com.todesktop.230313mzl4w4u92`    | `cursor-cdp.md`              |
| Ghostty          | `com.mitchellh.ghostty`            | `claude-code-tabs.md`        |

## Hard rules

- Never run a full recursive AX tree walk (15-20s on Safari). Always depth-limited (≤3 levels).
- Never poll AX at >20 calls/sec/pid (cmux #2985 stalls Cocoa main thread).
- Always subscribe `AXObserver` push notifications BEFORE the action fires.
- Always use deterministic ensemble first (L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30.
- Destructive actions (submit/send/delete) — single-channel only, never raced.
- Always strict-verify after every submit-class action (title diff + CTA absence + explicit confirmation phrase). See SKILL.md.

## Credits

The browser CDP daemon is vendored and namespaced from [browser-use/browser-harness](https://github.com/browser-use/browser-harness) (BSD-licensed). The cua-driver Swift sidecar comes from [trycua/cua](https://github.com/trycua/cua). Recovery patterns + race orchestration are original to this repo.

## License

See `LICENSE`.
