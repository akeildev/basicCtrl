# Slack — messaging

> Field-tested 2026-04-30 against macOS 26 Slack 4.40+ (Electron 30).

## Routing: use `mcp__basicCtrl__electron`

Slack is in the Electron registry (`com.tinyspeck.slackmacgap` →
default port 9222). Connect via:

```
mcp__basicCtrl__electron(action="connect",
                         bundle_id="com.tinyspeck.slackmacgap")
```

If Slack is already running without `--remote-debugging-port` (the
common case), the tool returns `needs_user_action=true` — ASK the
user before passing `quit_first=true`. Slack drops unsent message
drafts on quit; never auto-quit silently.

After connect, list workspace targets:

```
mcp__basicCtrl__electron(action="list_tabs",
                         bundle_id="com.tinyspeck.slackmacgap")
# Picks both pages and webviews. Filter by ".slack.com" in URL.
```

Switch to the workspace target, then run `js` / `click_xy` /
`type_text` against the selectors below.

## Workspace renderer selection

Slack opens MULTIPLE CDP page targets — one per workspace, plus the
LaunchPad / file-preview windows. Pick by URL:

```python
# T2's _pick_workspace_target() does this for you:
for t in target_infos:
    if t["type"] == "page" and ".slack.com" in t["url"]:
        return t
```

The leading `.` matters — it matches `https://app.slack.com/...` but
not `https://slack.com/marketing-page` (which doesn't have a workspace).

If the user has multiple workspaces, this returns the *first* one the
runtime registered. Per-workspace targeting is a future enhancement.

## Send a message

```python
# Click the message composer
TargetSpec(css="div[contenteditable='true'][role='textbox']")
# Type
action_type="type", payload={"text": "..."}
# Send button
TargetSpec(css="button[data-qa='texty_send_button']", label="Send")
```

The Send button rules over Enter — Slack will sometimes intercept
Enter for newline depending on user setting. Always use the explicit
button for determinism.

## Stable selectors

- **Channel list**: `[data-qa='channel_sidebar_name_button']`
- **Search**: `button[data-qa='top_nav_search']`
- **Reaction picker**: `button[data-qa='emoji_picker']`

## Traps

- **First launch grabs focus**: after `open -a Slack`, wait 2s before
  any CDP work — the splash window briefly steals the targetId.
- **Quitting Slack does not close CDP**: kill the process explicitly
  (`pkill -9 Slack`) when relaunching with `--remote-debugging-port`.
- **No SDEF**: Slack ships no AppleScript dictionary. T3 won't help;
  only T2 (CDP) and T4 (Vision OCR) can address Slack reliably.
