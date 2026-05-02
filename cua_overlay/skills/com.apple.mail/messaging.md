# Apple Mail — read / compose

> Field-tested 2026-05-02 against macOS 26 Mail 16.

## Heavy SDEF — prefer T3 over T1

Mail ships one of the richest AppleScript dictionaries in macOS. The
AX tree is *also* available but Mail's NSCollectionView for the
message list re-uses cells aggressively and walks confuse the
`AXValueChanged` push verifier. Default to T3.

## Stable patterns (T3)

- **Compose to recipient**:
  ```
  tell application "Mail"
      set m to make new outgoing message with properties {subject:"Hi", content:"Hello"}
      tell m
          make new to recipient at end of to recipients with properties {address:"x@example.com"}
      end tell
      send m
  end tell
  ```
  `send` is *terminal* — single-channel only (D-11 destructive).
- **Search inbox**: `tell application "Mail" to messages of inbox whose subject contains "..."` returns a list of message refs.
- **Read message body**: `tell application "Mail" to get content of message id 12345`
- **Mark as read**: `set read status of message id 12345 to true`

## Traps

- **`send` blocks until the SMTP roundtrip completes**: can hang 5-30s
  on flaky networks. Always wrap with as_daemon's `timeout_sec=30`
  override; otherwise the racing budget kills the fire mid-SMTP.
- **Message IDs are stable per session, not across launches**: cache
  the ID only within the same Mail-process lifetime. After `quit`,
  re-query.
- **AS reads against a closed mailbox return `missing value`**:
  always issue `tell account "..." to mailbox "INBOX"` to ensure the
  mailbox is loaded before reading.
- **Authentication dialogs are AX-modal**: a Keychain unlock prompt
  during `send` blocks all subsequent AS calls. Add a B5 recovery
  branch that detects the modal via L1 window-diff signal and prompts
  the user.
