# Ghostty — interact with Claude Code sessions across tabs

> Field-tested 2026-05-02. Ghostty terminal hosting many Claude Code
> tabs in one window. Pattern is general for any TUI in Ghostty tabs.

## Bundle ID

`com.mitchellh.ghostty`

## Mental model: tabs == windows

Ghostty exposes each tab as its own `CGWindowID`. `list_windows(pid)`
returns one record per tab — the on-screen one is the active tab,
the rest are off-screen. Title text reflects the running TUI's
window-title escape (Claude Code sets it from the current task).

Title prefix is the live-status indicator:

```
✳   waiting for human input (Claude finished a turn)
⠂ ⠐ ⠠ ⠰ ⠘ ⠈   spinner — Claude is currently working
```

Use the prefix to triage: `✳` tabs are idle and ready for a prompt;
spinner tabs are busy.

## Switching tabs: cmd+1 … cmd+9 (Ghostty default)

Visible in tab bar as `⌘1`, `⌘2`, etc. Sends the active tab to that
slot. Beyond 9 tabs you need a different shortcut (cmd+shift+[ ]).

The tab number you see in the tab strip is the cmd+N you press —
NOT the window_id. Use `list_windows(on_screen_only=true)` to confirm
which tab landed after a switch.

## CRITICAL: do NOT use `mcp__cua-maximalist__hotkey` + `type_text` to send keys to Ghostty tabs

Race condition: `hotkey(["cmd","1"])` issues the tab switch via
CGEvent, but `type_text` immediately after still resolves AX against
the **previously focused** AXTextArea. Result: your text lands in
the OLD tab's prompt instead of the new one.

The `key_combo_with_healing` + `type_with_healing` healing wrappers
have the same race for terminal apps because the healing layer's AX
ladder caches focus.

## The pattern that works: osascript via System Events

`osascript` keystroke goes through the macOS HID input pipeline
synchronously — the tab switch settles before the next keystroke
fires. Always activate Ghostty first.

```bash
osascript -e 'tell application "Ghostty" to activate'
sleep 0.3
osascript -e 'tell application "System Events" to tell process "Ghostty" to keystroke "1" using command down'
sleep 0.5     # let the tab switch render + focus settle
osascript -e 'tell application "System Events" to tell process "Ghostty" to keystroke "your prompt here"'
sleep 0.2
osascript -e 'tell application "System Events" to tell process "Ghostty" to key code 36'   # return
```

Key code 36 = Return. Use `key code 53` for Escape.

The 0.5s post-switch sleep is the load-bearing step. Anything below
~0.3s reintroduces the focus race.

## Recipe: send a prompt to one specific tab

```
1. list_windows(pid=ghostty_pid)
   → identify the target tab by title
   → note its position in the tab strip (1..N)
2. osascript activate Ghostty + cmd+N to switch
3. sleep 0.5
4. osascript keystroke "<prompt>" + key code 36
5. list_windows(pid, on_screen_only=true)
   → confirm title prefix flipped from ✳ to spinner
```

If the prefix is still `✳` after step 5, the prompt didn't reach the
input. Re-activate Ghostty and retry the keystroke.

## Recipe: "continue all my paused Claude Code tabs"

```
1. list_windows(pid=ghostty_pid)
2. filter records whose title starts with "✳ " — those are idle
3. for each idle tab (in tab-strip order):
     a. cmd+N to switch
     b. sleep 0.5
     c. keystroke "continue"
     d. key code 36 (return)
     e. sleep 1     ← let Ghostty's status indicator update
     f. list_windows(on_screen_only=true) → confirm spinner appeared
4. cmd+<your-original-tab-N> to return
```

## Recipe: check on a tab without disturbing it

Pure read-only — no keystrokes:

```
1. list_windows(pid)                         ← title shows status
2. screenshot(window_id=<target tab's id>)   ← read the visible content
   (works even when tab is off-screen, ScreenCaptureKit captures
    the window's last-rendered backing store)
```

`screenshot` does NOT switch the active tab. Safe to poll.

## CRITICAL: always screenshot BEFORE sending any prompt

The title prefix (`✳` / spinner) is a process-state indicator only.
It does NOT tell you:

- **What Claude actually asked.** Idle could mean "wrote a wrap-up,
  done intentionally" OR "asked a numbered menu and waiting for a
  pick" OR "asked a yes/no question" OR "is at 83% context and is
  done for the round." Sending `continue` blindly to all of these
  burns context and looks like you didn't read.
- **Context budget.** The status bar at the bottom of the screenshot
  shows current context % with a colored bar (green / yellow / red).
  At 75%+ the session is winding down — sending another prompt
  often just hits the limit faster.
- **Whether the previous prompt was a wrap-up.** Many sessions print
  a "NEXT after /clear" block with a self-written resume prompt. The
  right move there is `/clear` + paste the resume prompt verbatim,
  NOT `continue` (which discards the plan the session prepared).

Do this every round, even when you're polling a tab you sent a
prompt to a few seconds ago. Title-prefix lies (it can flip back to
`✳` between an in-flight turn ending and the user's next visible
input area). Screenshot tells the truth.

For each idle tab, the decision tree is:

```
read the screenshot →
  is it asking a numbered menu?  → pick the highest-leverage option
  is it asking yes/no?            → answer with the user's intent
  is it a wrap-up + resume plan?  → /clear + paste the resume prompt
  is it stuck on an error?        → diagnose, don't blanket "continue"
  is it just paused mid-thought?  → THEN "continue" is appropriate
```

## Recipe: send arbitrary text (not just "continue")

Same shape as above — replace the keystroke payload:

```bash
osascript -e 'tell application "System Events" to tell process "Ghostty" to keystroke "<your message>"'
osascript -e 'tell application "System Events" to tell process "Ghostty" to key code 36'
```

Multi-line input: send `\n` via `key code 36` (return) inside
Claude Code's prompt commits the message. To insert a literal
newline (shift+enter in Claude Code), use:

```bash
osascript -e 'tell application "System Events" to tell process "Ghostty" to key code 36 using shift down'
```

## Traps

- **Don't trust `verified` from the healing tools for Ghostty.** Target-less
  key combos always report `verified=False, confidence=0` — terminal
  state diff is invisible to the AX ladder. Verify by re-listing
  windows and checking the title-prefix change instead.

- **Tab status `✳` after sending "continue" is normal if Claude finished
  fast.** A short prompt + short response = back to ✳ within seconds.
  Don't conclude the keystroke failed — peek at the tab's screenshot
  to see whether a new turn appeared.

- **Ghostty tab indices are 1-based and visible in the tab strip.**
  If the user closes a tab, indices renumber. Re-run
  `list_windows` before each multi-tab operation.

- **Bash commands between MCP calls do NOT steal focus from Ghostty
  the way they do from other apps** — Ghostty IS where Claude Code
  is running, so it stays frontmost throughout. Still, defensively
  re-activate before the first keystroke of any new sequence.

- **`cmd+5` from the spawning Claude Code session sometimes does not
  return to that tab on the first try** — the keystroke can land
  during a tab-bar refresh and be dropped. Solve by re-activating
  Ghostty and re-sending; verify with `on_screen_only=true`.

- **Slash commands (`/clear`, `/compact`, …) collide with project-
  defined slash commands.** Many projects ship custom slash commands
  in `.claude/commands/`. Sending `/clear` to a tab whose project
  defines its own `/clear` runs the project command, not the built-in
  context-clear. Symptom: context % goes UP not down after `/clear`.
  Workaround: send `/help` first to peek at the command surface, OR
  ask the user before sending any slash command into a session you
  don't own.

- **Sending input while a turn is in flight queues it as the next
  user message; it does NOT interrupt.** If a tab shows a spinner,
  any keystroke you send waits until the current turn ends, then
  fires as a new prompt. To actually interrupt: send `escape` (key
  code 53), confirm interrupt landed via screenshot, THEN send the
  new prompt.

- **Don't conflate "title flipped to ✳" with "your prompt finished
  cleanly."** A short response that hit a context limit, a wrap-up,
  and a successful answer all leave `✳` behind. Always screenshot
  before deciding the run was a success.

## Why osascript instead of cua-driver primitives

cua-driver's `key_combo` + `type_text` are designed for graphical
apps where AX text fields are first-class. Ghostty's terminal
contents are a TUI rendered to a framebuffer — there's no
AXTextArea per tab. The "input area" Claude Code shows is a
character grid the terminal renders; macOS AX sees one big
AXTextArea per Ghostty WINDOW, and inserts there.

The framework's AX path inserts to that AXTextArea — but the cell
position used by AX `kAXSelectedText` doesn't match the terminal's
cursor, so the text either ends up in the wrong tab (if focus
hadn't settled) or nowhere visible.

osascript + `keystroke` posts HID events the terminal interprets the
same way it interprets a real keyboard — through the PTY. That's
the only path that lands cleanly inside a terminal pane.

## When to use this skill vs. browser-harness

- **Inside a Claude Code tab** → this skill (Ghostty key delivery).
- **Inside a Chrome/Safari tab where Claude.ai is open** →
  browser-harness (CDP-driven; clean DOM access).
- **Inside Claude Desktop app** → cua-driver / cua-maximalist
  with AX (it's an Electron app, AXTextArea works).
