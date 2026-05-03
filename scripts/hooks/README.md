# basicCtrl hooks

## learn_reminder.py

Stop hook that reminds Claude to call `mcp__basicCtrl__learn` when a
session discovered something non-obvious but didn't file the lesson.

### Install

Add to `~/.claude/settings.json` under `hooks.Stop`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/akeilsmith/Developer/basicCtrl/scripts/hooks/learn_reminder.py"
          }
        ]
      }
    ]
  }
}
```

Restart Claude Code. From now on, any session that ends without
calling `learn` despite hitting "trap" / "learned" / "non-obvious"
markers in the transcript will print a reminder to the agent's
next turn.

### Tune

To make it BLOCKING (forces agent to file a lesson before stopping),
edit the script and change `return 0` at the end to `return 2`.

### Disable

Remove the entry from settings.json or rename the script.
