#!/usr/bin/env bash
# basicCtrl one-command bootstrap.
# Idempotent: re-running reports "already configured" for every step.
# Safe: never replaces ~/.claude.json or ~/.claude/settings.json — always
# read → merge → write, with a .bak alongside before any mutation.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_JSON="$HOME/.claude.json"
SETTINGS_DIR="$HOME/.claude"
SETTINGS_JSON="$SETTINGS_DIR/settings.json"
HOOK_PATH="$REPO_DIR/scripts/hooks/learn_reminder.py"
VENV_PYTHON="$REPO_DIR/.venv/bin/python"

# --- pretty-print helpers ---------------------------------------------------
if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_FAIL=$'\033[31m'
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_FAIL=""; C_BOLD=""; C_DIM=""; C_RST=""
fi
ok()    { printf "  %s✓%s %s\n" "$C_OK"   "$C_RST" "$*"; }
skip()  { printf "  %s✓%s %s %s(already configured)%s\n" "$C_OK" "$C_RST" "$*" "$C_DIM" "$C_RST"; }
warn()  { printf "  %s!%s %s\n" "$C_WARN" "$C_RST" "$*"; }
fail()  { printf "  %s✗%s %s\n" "$C_FAIL" "$C_RST" "$*"; }
step()  { printf "\n%s→ %s%s\n" "$C_BOLD" "$*" "$C_RST"; }

# --- 1. Detect macOS + uv ---------------------------------------------------
step "1. Detect platform + uv"
if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "basicCtrl requires macOS (Darwin); got $(uname -s)"
  exit 1
fi
ok "macOS $(sw_vers -productVersion)"

if ! command -v uv >/dev/null 2>&1; then
  fail "uv not found on PATH. Install with: brew install uv"
  exit 1
fi
ok "uv $(uv --version 2>&1 | awk '{print $2}')"

# --- 2. uv sync + editable install ------------------------------------------
step "2. uv sync + uv pip install -e ."
cd "$REPO_DIR"
if uv sync --quiet; then
  ok "uv sync"
else
  fail "uv sync failed — re-run without --quiet to see error"
  exit 1
fi
if uv pip install -e . --quiet; then
  ok "uv pip install -e ."
else
  fail "editable install failed"
  exit 1
fi

# --- 2.5 Build cua-driver Swift sidecar -------------------------------------
# The MCP server proxies the Swift cua-driver binary. Without it, only the 5
# framework tools register; the 29 raw cua-driver primitives (launch_app,
# screenshot, page, etc.) are missing and the proxy logs
# upstream.cua_driver_not_found at boot.
step "2.5 Build cua-driver Swift sidecar"
CUA_DRIVER_SRC="$REPO_DIR/libs/cua-driver"
ARCH="$(uname -m)"  # arm64 or x86_64
CUA_DRIVER_BIN="$CUA_DRIVER_SRC/.build/${ARCH}-apple-macosx/release/cua-driver"
if [[ -x "$CUA_DRIVER_BIN" ]]; then
  skip "cua-driver binary ($CUA_DRIVER_BIN)"
elif [[ ! -d "$CUA_DRIVER_SRC" ]]; then
  warn "libs/cua-driver/ missing — vendored Swift source not present"
  warn "  29 raw cua-driver tools won't load; 5 framework tools still work"
elif ! command -v swift >/dev/null 2>&1; then
  warn "swift not on PATH — install Xcode Command Line Tools: xcode-select --install"
  warn "  Re-run installer after install. 5 framework tools still work without it."
else
  printf "  building cua-driver (release, ~30s)…\n"
  if ( cd "$CUA_DRIVER_SRC" && swift build -c release ) >/tmp/basicctrl-swift-build.log 2>&1; then
    if [[ -x "$CUA_DRIVER_BIN" ]]; then
      ok "cua-driver built → $CUA_DRIVER_BIN"
    else
      fail "swift build succeeded but binary missing at $CUA_DRIVER_BIN"
      sed 's/^/    /' /tmp/basicctrl-swift-build.log | tail -20
      exit 1
    fi
  else
    fail "swift build failed (see /tmp/basicctrl-swift-build.log):"
    tail -20 /tmp/basicctrl-swift-build.log | sed 's/^/    /'
    exit 1
  fi
fi
# Pass the binary path to the MCP server via env (step 4 reads this var).
# main.py:168 honors $CUA_DRIVER_BIN, so wiring it into the env block in
# ~/.claude.json means the proxy finds it without any PATH munging in the
# user's shell rc.
export CUA_DRIVER_BIN_FOR_INSTALLER=""
[[ -x "$CUA_DRIVER_BIN" ]] && export CUA_DRIVER_BIN_FOR_INSTALLER="$CUA_DRIVER_BIN"

# --- 3. Verify imports ------------------------------------------------------
step "3. Verify package imports"
import_err="$(uv run --quiet python - <<'PY' 2>&1
mods = [
    "basicctrl.mcp_server.main",
    "basicctrl.mcp_server.browser_tool",
    "basicctrl.mcp_server.electron_tool",
    "basicctrl.mcp_server.keystroke_tool",
    "basicctrl.mcp_server.form_fill_tool",
    "basicctrl.mcp_server.learn_tool",
]
import importlib
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as exc:
        print(f"FAIL {m}: {exc.__class__.__name__}: {exc}")
        raise SystemExit(1)
print("OK")
PY
)"
if [[ "$import_err" == "OK" ]]; then
  ok "all 6 MCP modules import cleanly"
else
  fail "import error:"
  printf '%s\n' "$import_err" | sed 's/^/    /'
  exit 1
fi

# --- 4. Wire MCP server into ~/.claude.json ---------------------------------
step "4. Register MCP server in ~/.claude.json"
[[ -f "$CLAUDE_JSON" ]] || echo '{}' > "$CLAUDE_JSON"

mcp_result="$(REPO_DIR="$REPO_DIR" CLAUDE_JSON="$CLAUDE_JSON" \
  CUA_DRIVER_BIN_FOR_INSTALLER="${CUA_DRIVER_BIN_FOR_INSTALLER:-}" python3 - <<'PY'
import json, os, shutil, sys
path = os.environ["CLAUDE_JSON"]
repo = os.environ["REPO_DIR"]
venv_py = f"{repo}/.venv/bin/python"
# Pass cua-driver binary path via env so the proxy doesn't depend on PATH —
# step 2.5 sets CUA_DRIVER_BIN_FOR_INSTALLER if the binary built successfully.
env_block = {}
cua_bin = os.environ.get("CUA_DRIVER_BIN_FOR_INSTALLER", "").strip()
if cua_bin:
    env_block["CUA_DRIVER_BIN"] = cua_bin
desired = {
    "type": "stdio",
    "command": venv_py,
    "args": ["-m", "basicctrl.mcp_server"],
    "cwd": repo,
    "env": env_block,
}
with open(path) as f:
    cfg = json.load(f)

# User-scoped registration: top-level mcpServers loads in every Claude Code
# session regardless of cwd. This is the right scope for a global skill that
# the user invokes from any project.
cfg.setdefault("mcpServers", {})
existing = cfg["mcpServers"].get("basicCtrl")

# Migration: if a previous installer wrote a project-scoped entry, drop it
# so we don't have two registrations fighting.
migrated_from = []
for proj_key in list(cfg.get("projects", {}).keys()):
    p = cfg["projects"][proj_key]
    if isinstance(p, dict) and "mcpServers" in p and "basicCtrl" in p["mcpServers"]:
        del p["mcpServers"]["basicCtrl"]
        migrated_from.append(proj_key)

if existing == desired and not migrated_from:
    print("ALREADY")
    sys.exit(0)
shutil.copy2(path, path + ".bak")
cfg["mcpServers"]["basicCtrl"] = desired
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
if migrated_from:
    print("MIGRATED " + ",".join(migrated_from))
else:
    print("WROTE")
PY
)"
case "$mcp_result" in
  ALREADY)    skip "basicCtrl MCP entry under top-level mcpServers";;
  WROTE)      ok "merged basicCtrl MCP entry → $CLAUDE_JSON (top-level mcpServers, backup: $CLAUDE_JSON.bak)";;
  MIGRATED*)  ok "promoted basicCtrl from project-scoped → top-level mcpServers (${mcp_result#MIGRATED }; backup: $CLAUDE_JSON.bak)";;
  *)          fail "unexpected result from JSON merge: $mcp_result"; exit 1;;
esac

# --- 5. Wire Stop hook into ~/.claude/settings.json -------------------------
step "5. Register Stop hook in ~/.claude/settings.json"
mkdir -p "$SETTINGS_DIR"
[[ -f "$SETTINGS_JSON" ]] || echo '{}' > "$SETTINGS_JSON"

# Make sure the hook itself is executable, otherwise Claude Code can't run it.
chmod +x "$HOOK_PATH" 2>/dev/null || true

hook_result="$(SETTINGS_JSON="$SETTINGS_JSON" HOOK_PATH="$HOOK_PATH" python3 - <<'PY'
import json, os, shutil, sys
path = os.environ["SETTINGS_JSON"]
hook = os.environ["HOOK_PATH"]
desired_inner = {
    "type": "command",
    "command": hook,
    "timeout": 10,
    "_basicCtrl": "learn-reminder",
}
desired_outer = {"matcher": "*", "hooks": [desired_inner]}
with open(path) as f:
    cfg = json.load(f)
cfg.setdefault("hooks", {})
cfg["hooks"].setdefault("Stop", [])
stop_list = cfg["hooks"]["Stop"]
# Dedupe by the _basicCtrl tag — survives matcher edits, command path edits.
for entry in stop_list:
    for h in entry.get("hooks", []):
        if h.get("_basicCtrl") == "learn-reminder":
            # Already wired. Update the command path in case the repo moved.
            if h.get("command") != hook:
                shutil.copy2(path, path + ".bak")
                h["command"] = hook
                with open(path, "w") as f:
                    json.dump(cfg, f, indent=2)
                print("UPDATED")
            else:
                print("ALREADY")
            sys.exit(0)
shutil.copy2(path, path + ".bak")
stop_list.append(desired_outer)
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
print("WROTE")
PY
)"
case "$hook_result" in
  ALREADY) skip "Stop hook (_basicCtrl: learn-reminder)";;
  UPDATED) ok "Stop hook command path updated → $hook (backup: $SETTINGS_JSON.bak)";;
  WROTE)   ok "Stop hook merged → $SETTINGS_JSON (backup: $SETTINGS_JSON.bak)";;
  *)       fail "unexpected result from settings merge: $hook_result"; exit 1;;
esac

# --- 6. Optional installs ---------------------------------------------------
step "6. Optional installs"
prompt_yn() {
  # $1=label, $2=default(y|n) — returns 0 for yes, 1 for no.
  local label="$1" def="$2" hint="[y/N]" reply
  [[ "$def" == "y" ]] && hint="[Y/n]"
  if [[ ! -t 0 ]]; then
    # Non-interactive (piped/CI) — take the default silently.
    [[ "$def" == "y" ]] && return 0 || return 1
  fi
  printf "  %s %s " "$label" "$hint"
  read -r reply
  reply="${reply:-$def}"
  [[ "$reply" =~ ^[Yy]$ ]]
}

# stockfish — required by Chess.app autoplay skill, optional otherwise.
if command -v stockfish >/dev/null 2>&1; then
  skip "stockfish ($(command -v stockfish))"
else
  if command -v brew >/dev/null 2>&1 && prompt_yn "Install stockfish (Chess.app autoplay skill)?" "n"; then
    if brew install stockfish; then
      ok "stockfish installed"
    else
      warn "stockfish install failed — Chess autoplay won't work, rest is fine"
    fi
  else
    warn "stockfish skipped — Chess.app autoplay won't work; install later via: brew install stockfish"
  fi
fi

# postgresql@16 — only needed for LangGraph durability. Proxy boots without it.
if brew list postgresql@16 >/dev/null 2>&1; then
  skip "postgresql@16 (LangGraph durability)"
else
  if command -v brew >/dev/null 2>&1 && prompt_yn "Install postgresql@16 (LangGraph durability — fully optional)?" "n"; then
    if brew install postgresql@16 && brew services start postgresql@16; then
      ok "postgresql@16 installed + started"
      warn "run 'bash scripts/init_postgres.sh' to provision the basicctrl DB"
    else
      warn "postgresql@16 install failed — durability disabled, rest is fine"
    fi
  else
    warn "postgresql@16 skipped — durability disabled (proxy still works)"
  fi
fi

# --- 7. Chrome remote-debug check ------------------------------------------
step "7. Chrome remote-debug probe (port 9222)"
chrome_app="/Applications/Google Chrome.app"
probe_chrome() {
  curl --max-time 1 --silent --fail "http://127.0.0.1:9222/json/version" >/dev/null 2>&1
}
if probe_chrome; then
  ok "Chrome DevToolsActivePort responding on 127.0.0.1:9222"
elif [[ ! -d "$chrome_app" ]]; then
  warn "Chrome not installed — skipping (browser bucket disabled until Chrome present)"
else
  warn "Chrome remote-debug not responding on 127.0.0.1:9222"
  if [[ -t 0 ]] && prompt_yn "Open chrome://inspect and walk through one-time setup?" "y"; then
    osascript \
      -e 'tell application "Google Chrome" to activate' \
      -e 'tell application "Google Chrome" to open location "chrome://inspect/#remote-debugging"' \
      >/dev/null 2>&1 || true
    cat <<'MSG'
    In Chrome:
      1. Tick "Allow remote debugging for this browser instance"
      2. (Chrome 144+) click "Allow" on the in-browser popup
    Then come back here and press Enter.
MSG
    read -r _ || true
    if probe_chrome; then
      ok "Chrome DevToolsActivePort now responding"
    else
      warn "still not responding — re-run installer or fix later, browser tool will say setup-needed"
    fi
  else
    warn "skipped — browser tool will surface setup-needed until Chrome is configured"
  fi
fi

# --- 8. Smoke-test all 5 MCP tool registrations -----------------------------
# Run python with stderr captured separately so structlog INFO lines don't
# pollute the OK marker on stdout. Only show stderr if the test fails.
step "8. Smoke-test MCP tool registration"
smoke_err_file="$(mktemp)"
smoke_stdout="$(uv run --quiet python - 2>"$smoke_err_file" <<'PY'
from mcp.server.fastmcp import FastMCP
from basicctrl.mcp_server.browser_tool import register_browser_tool
from basicctrl.mcp_server.electron_tool import register_electron_tool
from basicctrl.mcp_server.keystroke_tool import register_keystroke_tool
from basicctrl.mcp_server.form_fill_tool import register_form_fill_tool
from basicctrl.mcp_server.learn_tool import register_learn_tool
m = FastMCP("smoke-test")
register_browser_tool(m)
register_electron_tool(m)
register_keystroke_tool(m)
register_form_fill_tool(m)
register_learn_tool(m)
print("OK")
PY
)"
if [[ "$smoke_stdout" == "OK" ]]; then
  ok "browser + electron + keystroke + form_fill + learn registered cleanly"
  rm -f "$smoke_err_file"
else
  fail "smoke-test failed:"
  printf '%s\n' "$smoke_stdout" | sed 's/^/    stdout: /'
  sed 's/^/    stderr: /' "$smoke_err_file"
  rm -f "$smoke_err_file"
  exit 1
fi

# --- 9. Final summary -------------------------------------------------------
step "Done — basicCtrl bootstrap complete"
cat <<EOF

  Repo            $REPO_DIR
  Venv python     $VENV_PYTHON
  MCP entry       $CLAUDE_JSON  (top-level mcpServers.basicCtrl — loads in every session)
  Stop hook       $SETTINGS_JSON  (hooks.Stop[*]._basicCtrl=learn-reminder)
  Hook script     $HOOK_PATH

  ${C_BOLD}Next:${C_RST} restart Claude Code so it picks up the new MCP server + hook.

  Try:
    "use basicCtrl skill to add a calendar event called 'Dentist' for Friday at 3pm"

EOF
