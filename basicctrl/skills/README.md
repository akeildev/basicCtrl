# basicctrl/skills/ — per-app field knowledge

> Borrowed wholesale from [browser-harness's `domain-skills/`](https://github.com/browser-use/browser-harness/tree/main/domain-skills)
> pattern. Skills capture **the durable shape of an app** so future agents on
> the same target don't pay the same exploration tax twice.

## Layout

```
skills/
├── README.md                                this file
├── loader.py                                optional: surface skill text to
│                                            cognition layer prompts
└── <bundle_id>/
    └── <action_or_topic>.md                 markdown only, no code
```

Examples:
- `com.google.Chrome/general.md` — Chrome CDP probe ports, user-data-dir lock
- `com.tinyspeck.slackmacgap/messaging.md` — workspace renderer URL filter
- `com.apple.calculator/arithmetic.md` — button label quirks, AC vs C, NSUserDefaults state pollution

## What goes in a skill

The **map, not the diary** (browser-harness SKILL.md§"What a domain skill should capture").

- URL/window patterns + how to identify the right target
- Stable selectors that beat the obvious one (or warn off CSS modules)
- Private APIs the app calls (often 10× faster than DOM scraping)
- Framework quirks (React-combobox-only-commits-on-Escape style)
- Waits + the **reason** they're needed
- Traps + selectors that *don't* work
- **Field-tested date** at the top, so future agents can detect drift

## What does NOT go in a skill

- Raw pixel coordinates (break on viewport, zoom, layout)
- Run narration / step-by-step of the specific task you just did
- Secrets, cookies, session tokens, user-specific state

## How an agent should use skills

1. **Before exploring**: check if `skills/<bundle_id>/` exists. If yes,
   read it. If no, you're discovering — be ready to PR back.
2. **During execution**: when you find a non-obvious pattern (a stable
   selector, a private API, a wait reason), capture it.
3. **Before finishing**: if you learned anything durable, write a new
   skill file or amend an existing one.

The goal is the same as browser-harness: **the next agent on this app
should not pay the tax you just paid**.
