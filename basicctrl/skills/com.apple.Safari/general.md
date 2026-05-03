# Safari — general control

> Field-tested 2026-05-02 against macOS 26 Safari 18.

## When to use Safari vs Chrome

For *basicCtrl's own integration tests* prefer **Chrome** (the
cdp-chromium e2e gate uses Chrome) because Safari does not expose CDP
without the user manually enabling Develop menu → Allow Remote
Automation. For real user workflows where the user *is* a Safari user,
T1 (AX) + T3 (AppleScript SDEF) are the right path.

## Stable patterns (T3 SDEF)

- **Get current URL**: `tell application "Safari" to get URL of current tab of front window`
- **Open URL in front tab**: `tell application "Safari" to set URL of current tab of front window to "https://..."`
- **Open URL in new tab**: `tell application "Safari" to make new tab at end of tabs of front window with properties {URL: "..."}`
- **Get page text**: `tell application "Safari" to do JavaScript "document.body.innerText" in current tab of front window` — *requires* Develop → Allow JavaScript from Apple Events grant.

## Stable patterns (T1 AX)

- Address bar: `AXTextField` with `AXIdentifier == "WEB_BROWSER_ADDRESS_AND_SEARCH_FIELD"`
- Reload button: `AXButton` with title `"Reload this page"`
- Back / Forward: `AXToolbar > AXGroup > AXButton` titled "Back" / "Forward"
- Tab bar: `AXTabGroup` with one `AXRadioButton` per tab

## Traps

- **JavaScript-via-AppleEvent is gated**: every `do JavaScript`
  bombs with -1731 unless the user has ticked Develop → "Allow
  JavaScript from Apple Events". The test harness must check + skip.
- **Reader mode hides the page DOM**: in Reader mode, `AXWebArea`
  collapses to a single text blob. Detect via the `AXIdentifier
  ReaderControlsViewController` toolbar button and exit Reader mode
  before scraping.
- **iCloud Tabs sync delay**: opening a URL on Mac then reading "front
  tab" within 200ms can return the previous URL while sync churns.
  Wait for `Page.loadEventFired`-equivalent (poll URL until stable).
- **Private browsing windows**: have separate AX tree; `front window`
  may not be what you expect if user has both modes open. Filter by
  `AXTitle` or window count.
