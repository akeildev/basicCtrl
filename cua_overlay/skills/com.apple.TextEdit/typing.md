# TextEdit — typing into a document

> Field-tested 2026-05-02 against macOS 26 TextEdit 1.21.

## Why this app is the easy mode

TextEdit is the most cooperative target for the framework:

- Full AppleScript SDEF — T3 tells `tell application "TextEdit" to set text of front document to "..."` and it works first try.
- Real AX tree — T1 walks AXScrollArea > AXTextArea cleanly (no React shadow-DOM drama).
- Fires `AXValueChanged` on the text area — L0 push verifier sees every keystroke.

When debugging healing-tool regressions, **reproduce against TextEdit
before Calculator** — TextEdit gives you signal at every layer.

## Open a document

```python
# Via AppleScript (preferred — also handles "no document open" case)
tell application "TextEdit"
    activate
    if (count of documents) = 0 then
        make new document
    end if
end tell
```

The `make new document` is idempotent inside the if-guard — safe to
call from a recovery branch.

## Stable patterns

- **Type into front doc**: `tell application "TextEdit" to set text of front document to "..."`
- **Append**: `tell application "TextEdit" to set text of front document to (text of front document) & "..."`
- **Read content**: `tell application "TextEdit" to get text of front document`
- **Save as**: requires GUI dialog, drops out of pure-AS land — use C2 AX click on the Save button.

## Traps

- **`activate` warmup**: first `tell application "TextEdit"` call after
  process restart can take 1-3s while macOS launches it. The
  as_daemon timeout (8s default) covers this; don't shrink it.
- **TCC Automation grant**: System Settings → Privacy → Automation →
  Python → TextEdit must be ON. Without it, every `tell` call returns
  AppleEvent error -1743. Document this in your test setup.
- **Untitled docs are unsaved**: a brand-new doc has no `path`; AS
  read of `path` returns missing value. Filter with
  `if path of front document is missing value then ...`.
