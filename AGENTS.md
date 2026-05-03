# AGENTS.md — instructions for AI agents working in this repo

This file is the source of truth for any AI coding agent (Claude Code, Codex, Cursor, Aider) opening this repo. Read it before touching code.

## Project

**basicCtrl** — self-healing autonomous macOS computer-use framework. The skill name, MCP server name, and GitHub repo name are all `basicCtrl`. The Python package is `basicctrl` (PEP 8 lowercase). The MCP tool prefix is `mcp__basicCtrl__*`.

## What lives where

```
basicctrl/                ← Python package (formerly cua_overlay)
  browser/                ← vendored CDP daemon (browser-harness pattern)
  mcp_server/
    main.py               ← MCP proxy entry point
    healing_tools.py      ← 8 *_with_healing tools wrapping RaceOrch + RecoveryOrch
    browser_tool.py       ← mcp__basicCtrl__browser (CDP-driven web ops)
  translators/            ← T1 AX, T2 CDP, T3 AS, T4 Vision, T5 Pixel
  recovery/branches/      ← B1-B5 recovery branches
  actions/                ← race orchestrator, channels, idempotency
  skills/<bundle_id>/     ← per-app field-tested recipes (auto-written + hand-curated)
  state/, agents/, profile/, swift/, visualizer/

libs/cua-driver/          ← the upstream Swift driver (DO NOT EDIT — overlay only)
.planning/                ← phase plans, research, requirements; treat as read-only
tests/                    ← pytest unit + integration
scripts/                  ← e2e runners, doctor, demo scripts
CLAUDE.md                 ← project conventions, hard rules, status
```

## Hard rules (do not break)

- **Never edit Swift code under `libs/cua-driver/`.** Overlay-only project.
- **Never run a full recursive AX tree walk.** 15-20s on Safari. Always depth-limited (≤3 levels).
- **Never poll AX at >20 calls/sec/pid.** cmux #2985 stalls Cocoa main thread. Subscribe `AXObserver` push events instead.
- **Always use deterministic ensemble first** (L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30.
- **Destructive actions** (submit/send/delete) are single-channel only — never raced. Enforced server-side in `RaceOrchestrator.resolve_race_policy`.
- **Always strict-verify after every submit-class action** — title diff + CTA absence + explicit confirmation phrase. See `~/.claude/skills/basicCtrl/SKILL.md` "MANDATORY: strict-verify every submit-class action in the browser" section. Substring-matching the page text is NOT enough — "on the list" matches "Get on the list" and produces false positives.

## How to make changes

The repo uses a GSD (Get Shit Done) workflow. Slash commands:

- `/gsd-quick` — small fixes, doc updates, ad-hoc tasks
- `/gsd-debug` — investigation + bug fixing
- `/gsd-execute-phase` — planned phase work (see `.planning/phases/`)

Don't make direct edits outside a GSD workflow unless explicitly told to bypass it.

## When you finish a successful task

Two artifacts MUST be written before reporting success:

1. **Per-app skill markdown** at `basicctrl/skills/<bundle_id>/<topic>.md` — bundle ID, mental model, working recipes (numbered steps with verify points), traps, field-tested date. New topic file alongside existing ones, don't append unrelated stuff.

2. **FAISS recipe** via `register_task_complete(task_label, task_class, app_bundle_id)`. Only fires if the run used `*_with_healing` wrappers (raw clicks/keys aren't recorded). If raw, skip FAISS but write the markdown anyway.

The markdown is what the next agent reads. The FAISS recipe is what the planner reads. Both compound.

## Browser automation routing

Chromium-class targets (Chrome, Brave, Edge, Arc) → `mcp__basicCtrl__browser`, NOT `*_with_healing` AX click. The browser tool wraps the vendored CDP daemon; it's strictly faster and sees iframes/shadow DOM that AX flattens.

For terminal apps (Ghostty, iTerm2, Alacritty), use `osascript via System Events keystroke`, NOT `key_combo_with_healing` — the latter races AX text insertion against keystroke and lands text in the wrong tab. See `basicctrl/skills/com.mitchellh.ghostty/claude-code-tabs.md`.

## Local dev

```bash
uv sync                                  # set up .venv from lockfile
uv pip install -e .                      # editable install
uv run pytest tests/unit                 # ~525 tests, all should pass
uv run pytest tests/integration -m e2e   # 27 integration gates
uv run python -m basicctrl.mcp_server    # run the MCP server standalone
```

## Tech stack (locked — see CLAUDE.md for the full table)

Python 3.12 + uv. PyObjC 12.1 for macOS bridges. cdp-use for the CDP WS. mlx-vlm for UI-TARS-1.5 grounding. faiss-cpu for episodic memory. structlog for the action log. langgraph-checkpoint-postgres for durability. Swift 6.0 sidecars for the visualizer + CGEvent learning recorder.

Don't add new heavy deps without proposing a tradeoff in `.planning/research/STACK.md`.

## Credits

Browser CDP daemon vendored + namespaced from [browser-use/browser-harness](https://github.com/browser-use/browser-harness) (BSD). Swift driver from [trycua/cua](https://github.com/trycua/cua).
