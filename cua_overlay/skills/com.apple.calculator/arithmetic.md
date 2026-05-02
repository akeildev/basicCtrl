# Apple Calculator — arithmetic

> Field-tested 2026-05-01 against macOS 26 Calculator 10.16.

## Driving keys

Use `click_with_healing` with `TargetSpec(label="<button>")`. Labels
match the visible button glyphs:

| Visible | TargetSpec.label  |
|---------|-------------------|
| 0–9     | `"0"`, `"1"`, ... |
| +       | `"+"` or `"Add"`  |
| −       | `"−"` (minus sign U+2212) or `"Subtract"` |
| ×       | `"×"` or `"Multiply"` |
| ÷       | `"÷"` or `"Divide"`  |
| =       | `"="` or `"Equals"`  |
| AC / C  | `"All Clear"`, `"Clear"`, `"AC"`, `"C"` (try in order) |

T1 AX prefers label exact match; if the keypad button has a localized
title (rare), fall back to text-content.

## Reading the display

The display element is `AXScrollArea > AXStaticText` at the **top of
the window** (well above the button row). It is what fires
`AXValueChanged` notifications — the keypad buttons themselves do NOT
fire any notification on press (F1).

```python
# To read display value:
calc_app = AXUIElementCreateApplication(pid)
windows = AXUIElementCopyAttributeValue(calc_app, "AXWindows")
display = walk_subtree(windows[0], depth=3, predicate=role=="AXStaticText")
value = AXUIElementCopyAttributeValue(display, "AXValue")
```

## State pollution traps

### F1: Keypad buttons fire no notification

`AXValueChanged` is fired by the *display*, not the button. L0 push
verifier MUST subscribe at `AXApplication` root (not the button), or
it sees no signal and reports verified=False even on a successful
click. The F9 fix in `RaceOrchestrator` does this correctly.

### F14: NSUserDefaults persists state across `pkill`

Calculator restores `RestoreInputValue` and `LastResultValue` from
`~/Library/Preferences/com.apple.calculator.plist` on launch.
**`pkill -9` does not clear them.**

If you click `5 + 3 =` to get 8, kill Calculator, relaunch, and click
`AC, 5, +, 3, =` you'll see `18` (the stale `1` prefix from the
restored buffer composes with the new keystrokes; AC clears the
display but not the operation buffer).

**Mitigation:** before any test, run:

```bash
defaults delete com.apple.calculator
```

`scripts/verify-everything.sh` does this between every Calculator-
touching gate.

### Stuck AX state

After 50+ rapid AX calls, Calculator's window can enter a state where
the AX tree under it has zero AXButton descendants. Closing +
relaunching does NOT always recover; only restarting macOS (or
waiting tens of minutes) reliably restores the UI. The
`calculator_pid` fixture in `tests/integration/conftest.py` has an
AX-readiness probe that detects this and `pytest.skip()`s.

## Recommended patterns

- Always click `AC` (or `All Clear`) first to defeat F14.
- Race policy: `RACE` is safe for keypad clicks (idempotent), but
  destructive calc operations (none exist here) would still go single-
  channel per D-11.
- Verify via the display element subscription, not the button.
