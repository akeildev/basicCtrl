# Prompt — paste into fresh Claude Code session to finish bootstrap

Copy everything below the `---` line into a new session at
`~/Developer/basicCtrl`. The agent will build, test, commit, and push
the bootstrap installer that makes basicCtrl zero-touch for new users.

---

You are picking up work on **basicCtrl** at `/Users/akeilsmith/Developer/basicCtrl`. The framework is a self-healing macOS computer-use harness with 4 routing buckets (AX, Browser, Electron, Terminal) plus a web-form-fill tool and a self-improve loop. It's working but installation still has 7 manual steps. Your job: write `scripts/install.sh` so a new user runs ONE command and everything works.

## Read these files first to understand state

```
basicctrl/mcp_server/main.py            ← all 4 MCP tools registered here
basicctrl/mcp_server/browser_tool.py    ← Chrome CDP bucket
basicctrl/mcp_server/electron_tool.py   ← Electron CDP bucket (per-app)
basicctrl/mcp_server/keystroke_tool.py  ← Terminal osascript bucket
basicctrl/mcp_server/form_fill_tool.py  ← Web form RSVP/signup
basicctrl/mcp_server/learn_tool.py      ← Qualitative self-improve
scripts/hooks/learn_reminder.py         ← Stop hook (already exists)
scripts/hooks/README.md                 ← manual install steps for the hook
~/.claude/skills/basicCtrl/SKILL.md     ← top-level skill doc
basicctrl/skills/_generic/web-form-fill.md  ← cross-app pattern
basicctrl/skills/com.apple.Chess/autoplay-with-stockfish.md
basicctrl/skills/com.mitchellh.ghostty/claude-code-tabs.md
README.md                               ← user-facing readme
AGENTS.md                               ← agent rules
```

## What `scripts/install.sh` must do

Idempotent — running twice should be a no-op. Each step should print a clear `✓` / `✗` line. Write it as bash + small embedded python where needed.

```
1. Detect macOS + uv
   - check `uname -s` is Darwin
   - check `uv --version` works; if not, suggest `brew install uv` and exit
2. uv sync && uv pip install -e .
   - cwd is repo root
3. Verify imports work
   - uv run python -c "from basicctrl.mcp_server.main import ..."
   - if fail, show which import broke
4. Wire MCP server into ~/.claude.json
   - read existing ~/.claude.json with python json
   - merge a new project entry under projects.<absolute repo path>
   - schema:
       "mcpServers": { "basicCtrl": { "type": "stdio",
         "command": "<repo>/.venv/bin/python",
         "args": ["-m", "basicctrl.mcp_server"],
         "cwd": "<repo>", "env": {} } }
   - if entry exists with same path, leave alone (idempotent)
   - back up ~/.claude.json to ~/.claude.json.bak before write
5. Wire Stop hook into ~/.claude/settings.json
   - read existing settings.json (may not have hooks.Stop key)
   - merge a new entry under hooks.Stop array:
       { "matcher": "*", "hooks": [{
         "type": "command",
         "command": "<repo>/scripts/hooks/learn_reminder.py",
         "timeout": 10,
         "_basicCtrl": "learn-reminder" }] }
   - dedupe if entry already exists (match on _basicCtrl tag)
   - back up settings.json to settings.json.bak before write
6. Optional installs (prompt y/n)
   - stockfish (for Chess.app autoplay) — `brew install stockfish`
   - postgresql@16 (for LangGraph durability — optional)
7. Chrome remote-debug check
   - probe http://127.0.0.1:9222/json/version
   - if dead AND user has Chrome installed: open chrome://inspect/#remote-debugging
     via `osascript -e 'tell application "Google Chrome" to activate' \
                  -e 'tell application "Google Chrome" to open location \"chrome://inspect/#remote-debugging\"'`
   - print: "Tick 'Allow remote debugging for this browser instance' in
     Chrome → click Allow on the popup. One-time. Press Enter when done."
   - re-probe; if still dead, warn but don't fail (user might do it later)
8. Smoke-test all 4 MCP tool registrations
   - uv run python -c "from mcp.server.fastmcp import FastMCP;
     from basicctrl.mcp_server.{browser_tool,electron_tool,keystroke_tool,form_fill_tool,learn_tool} import register_*;
     m = FastMCP('test'); ...; print('ok')"
9. Final summary
   - print where each thing got installed
   - print "RESTART CLAUDE CODE for changes to take effect"
   - print example: 'Try: "use basicCtrl skill to add a calendar event"'
```

## After install.sh works

1. Update README.md so the install section becomes one line:
   ```bash
   git clone https://github.com/akeildev/basicCtrl.git
   cd basicCtrl && bash scripts/install.sh
   # restart Claude Code, done
   ```
2. Update top of `~/.claude/skills/basicCtrl/SKILL.md` to mention bootstrap.
3. Test by:
   - `git stash` any uncommitted changes
   - run `bash scripts/install.sh` end-to-end (idempotent — should report "already configured" for each step)
   - verify `claude mcp list` shows basicCtrl OR ~/.claude.json has the entry
   - verify settings.json has the Stop hook
4. Commit `scripts/install.sh` + README.md update with message:
   ```
   feat(install): one-command bootstrap (scripts/install.sh)

   - merges MCP server entry into ~/.claude.json
   - merges Stop hook into ~/.claude/settings.json
   - prompts for stockfish + Chrome remote-debug setup
   - smoke-tests all 4 MCP tools
   - idempotent: re-running reports "already configured"

   Closes the zero-touch install gap. New users run one command.
   ```
5. `git push`

## Hard rules

- **Never replace** the user's `~/.claude.json` or `~/.claude/settings.json`. Always read → merge → write. The user has many other entries that must be preserved.
- **Always back up** before write (`.bak` next to the file).
- **Idempotent** — re-running the install must never duplicate entries or break existing config.
- **Use jq + python** for JSON merges, not `sed` (settings.json is too complex for sed).
- The repo's `~/.claude/skills/basicCtrl/SKILL.md` and `basicctrl/skills/_generic/web-form-fill.md` are documentation only — don't touch them in install.sh.

## Save lessons via the learn tool

When you finish, call `mcp__basicCtrl__learn(target='generic', title='install.sh trap or finding', body='...')` for anything non-obvious you discovered while building the installer (e.g. macOS-vs-Linux differences, jq merge gotchas, Chrome's remote-debug auto-detection edge cases). The Stop hook will remind you if you forget.

## Verify before reporting done

Run install.sh on a clean state to prove:
- `~/.claude.json` has the basicCtrl MCP entry under the repo's project key
- `~/.claude/settings.json` has the Stop hook with `_basicCtrl: learn-reminder` tag
- `uv run python -m basicctrl.mcp_server` starts without error (Ctrl+C immediately to test)
- Re-running install.sh prints "already configured" for each step (idempotent)

If any step fails, fix the script + re-test, don't ship a broken installer.
