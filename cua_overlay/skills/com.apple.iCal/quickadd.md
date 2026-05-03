# Calendar.app — Quick Add event flow

> Field-tested 2026-05-03. macOS 26 Tahoe, Calendar 17.x.

## Bundle ID

`com.apple.iCal` (yes, the bundle ID is the legacy iCal name even though
the app is called Calendar).

## Recipe: create one event by natural-language

```
1. cmd+n               opens the QuickEvent popover. Calendar must have
                       a visible on-screen window OR be activated first.
                       Hidden / off-Space → cmd+n is silently dropped.

2. (verify) AXTextField id=QuickEventCell appears in tree. If absent
   after 1.5s, the popover did not open — re-AXRaise the window and
   retry cmd+n once.

3. type_with_healing   "<title> <date> at <time>" — natural language.
                       Calendar's NL parser handles "tomorrow",
                       "May 3", "next Tuesday", "5pm", "17:00", etc.

4. return              COMMITS the event into the selected calendar
                       AND opens the inline detail editor for further
                       refinement. The event is already saved at this
                       point — the editor is optional.

5. (verify) AXStaticText with title appears under the day's AXList in
   the calendar grid. Confirm before moving on.

6. cmd+w               closes the inline detail editor cleanly.
                       The event stays.
```

## Trap: escape cancels in flight

**Do NOT press `escape` to dismiss the detail editor opened by step 4.**

Escape on the editor cancels the in-flight commit. Even though step 4's
Return appears to have committed the event, escape rolls it back. We
lost 4 events this way before discovering this.

`cmd+w` is the safe close — preserves the committed event.

## Trap: window must be visible before cmd+n

Calendar's main window is often off-screen / on another Space. Menu
shortcuts (cmd+n, cmd+s, …) are only delivered to the **key** app's
windows. If Calendar is hidden, cmd+n fires through CGEvent but
Calendar's event handler doesn't process it.

Pre-flight: `ensure_real_window(pid, activate_if_not_frontmost=True)`
or AppleScript `tell application "Calendar" to activate` before the
first keystroke. The framework's target-less helper does this
automatically (Fix #4).

## Loop: many events back-to-back

Between events, close the prior detail editor with `cmd+w` BEFORE
issuing the next `cmd+n`. Otherwise the second cmd+n fires while the
editor is still focused — nothing happens, or worse, the cmd+n hits
the wrong field.

Verified working sequence for 8 sequential events at 6:00 AM:

```python
for date_str in dates:
    cmd+n                                         # open quickadd
    snapshot → expect "QuickEventCell" present
    type_with_healing(f"reading {date_str} at 6am")
    return                                        # commit + open editor
    snapshot → expect title visible in calendar grid
    cmd+w                                         # close editor (NOT escape)
```

8/8 events landed clean using this exact loop.

## AX shape (post-cmd+n)

```
AXPopover
  AXStaticText "Create Quick Event"
  AXTextField id=QuickEventCell           ← type into this
  AXButton (New Event) id=QuickEventNewEventButton
  AXButton (New Reminder) id=QuickEventNewReminderButton
```

The AXButton "New Event" can be clicked directly via element_index
instead of pressing Return — but Return is shorter and works
identically. Both commit and then open the detail editor.

## What NOT to do

- AppleScript `make new event with properties {…}` works but bypasses
  the GUI — defeats the point of testing the framework's GUI driver.
- Two Calendar game windows simultaneously open: rare in Calendar
  (unlike Chess.app), but if it happens, AXFocusedWindow may resolve
  to the wrong one. Use list_windows + on_screen_only=True to pick
  the visible one.
- Don't AXSet value on the QuickEventCell directly — Calendar's NL
  parser only fires on Return / button-press, not on programmatic
  value-set. Type-then-Return is the only path that triggers parsing.
