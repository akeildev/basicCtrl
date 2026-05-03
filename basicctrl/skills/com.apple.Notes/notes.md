# Apple Notes — read / write

> Field-tested 2026-05-02 against macOS 26 Notes 4.13.

## SDEF + AX both work

Notes has a complete AppleScript dictionary AND a clean AX tree
(NSTextView under AXScrollArea). Either path works; T3 is faster for
bulk reads/writes, T1 is faster for "click on a specific note" by
visible title.

## Stable patterns (T3)

- **Create note**:
  ```
  tell application "Notes"
      tell account "iCloud"
          tell folder "Notes"
              make new note with properties {name:"Meeting prep", body:"<h1>Hi</h1>"}
          end tell
      end tell
  end tell
  ```
  `body` accepts limited HTML — `<h1>` `<p>` `<ul>` `<a>` `<b>` `<i>`.
- **Read all notes in folder**: `tell application "Notes" to tell folder "Notes" of account "iCloud" to get name of every note`
- **Search by title**: `tell application "Notes" to notes whose name is "..."`

## Stable patterns (T1)

- Note list: `AXScrollArea` containing `AXOutline` of `AXRow`s;
  each row's `AXLabel` is the note title.
- Note body: focused `AXTextArea` on the right pane.
- New-note button: toolbar `AXButton` titled `"New Note"`.

## Traps

- **iCloud sync lag**: a note created via T3 doesn't appear in the AX
  tree until iCloud sync runs (1-5s). If a recovery branch needs to
  click on the just-created note, sleep 2s + retry.
- **Two accounts with same folder name**: `folder "Notes"` ambiguous
  if the user has both iCloud AND On-My-Mac accounts. Always qualify
  with `tell account "iCloud"`.
- **`body` is HTML on write but plain text on read** in older macOS
  (≤14). On macOS 26 both directions are HTML; check Notes version
  before assuming.
- **Pinned notes appear at top of AXOutline regardless of sort
  order** — index-based addressing breaks. Always select by `AXLabel`.
