# Cursor — Electron CDP control

> bundle_id: `com.todesktop.230313mzl4w4u92`
> Field-tested 2026-04-29 against Cursor 0.40+ (Electron 30, VS Code base).

## Routing: use `mcp__basicCtrl__electron`

Cursor is in the Electron registry (default port 9225). Connect via:

```
mcp__basicCtrl__electron(action="connect",
                         bundle_id="com.todesktop.230313mzl4w4u92")
```

If Cursor is already running without `--remote-debugging-port`, the
tool returns `needs_user_action=true`. Ask the user to save unsaved
files, then retry with `quit_first=true`.

The Cursor AI sidebar runs in a webview — surface it via:

```
mcp__basicCtrl__electron(action="list_tabs",
                         bundle_id="com.todesktop.230313mzl4w4u92",
                         include_webview=True)
```

Two targets typically appear: `vscode-file://...` (main editor) and
`vscode-webview://...` (the AI sidebar). Pick by URL and switch via
`action="switch_tab"`.

## Relaunch with --remote-debugging-port

Cursor (like all Electron apps) ignores `--remote-debugging-port`
unless it's passed at launch. The framework's known_apps entry sets
`cdp_after_relaunch=True`, meaning Plan 02-11's healing tool prompts
the user once to relaunch:

```bash
killall Cursor
"/Applications/Cursor.app/Contents/MacOS/Cursor" --remote-debugging-port=9222 &
```

Without this, T2 returns None for Cursor and the orchestrator falls
through to T1 (AX) — which works for many actions but is slower and
misses webview-rendered DOM (e.g. the AI sidebar).

## Workspace renderer filter

Cursor has multiple page targets (one per editor window, plus the
extension host). Filter by URL prefix `vscode-`:

```python
# basicctrl/translators/t2_cdp.py:_pick_workspace_target
if bundle_id == "com.todesktop.230313mzl4w4u92":
    for t in target_infos:
        if t["type"] == "page" and t["url"].startswith("vscode-"):
            return t
```

Two `vscode-` URLs typically appear:
- `vscode-file://vscode-app/...` — the main editor renderer (use this)
- `vscode-webview://...` — webview iframe content (the AI sidebar);
  attaches independently, useful for sidebar interactions only

## Stable selectors

- **Editor**: `.monaco-editor textarea` (the hidden textarea Monaco
  intercepts keystrokes through; useful for `Input.insertText`)
- **Command palette**: `.quick-input-widget input` after `cmd+shift+p`
- **AI sidebar input**: `[data-cursor='chat-input']` (added by Cursor
  team's UI overlay; survives major refactors so far)
- **File explorer item**: `[data-keybinding-context]` per row

## Traps

- **Monaco intercepts most key events**: standard `Input.dispatchKey`
  on the .monaco-editor element doesn't insert text. Use
  `Input.insertText` against the focused textarea, OR send keystrokes
  to the underlying hidden textarea after focus.
- **AI sidebar is a webview**: attaches as a separate target with type
  "webview". `Target.getTargets` lists it; you may need to attach to
  it in addition to the main editor.
- **Cursor overlays can swallow clicks at the compositor level too**:
  modal "trusted-folder" dialogs intercept `Input.dispatchMouseEvent`
  even though the click coordinates are right. Detect via L1 dialog
  signal (`Page.javascriptDialogOpening`) and dismiss via Escape
  before retrying.
- **Settings → Editor → "Allow scripting"** is OFF by default for new
  installs; some `Runtime.evaluate` calls return RangeError. The
  framework's L0+L1 fallbacks cover this.
