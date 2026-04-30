#!/bin/bash
# Ralph-loop Stop hook — captures autonomous-run state snapshot.
# Runs whenever Claude Code stops in this project.
# Writes a timestamped entry to .planning/RALPH-HANDOFF.md "History" section
# so the next ralph-loop iteration sees a fresh state pin.

set -uo pipefail

REPO=/Users/akeilsmith/dev/cua-maximalist
HANDOFF="$REPO/.planning/RALPH-HANDOFF.md"
RALPH_STATUS="$REPO/.claude/ralph-loop.local.md"

# Hook stdin is JSON with session_id; we mostly ignore it.
read -r STDIN_JSON || true

if [[ ! -f "$HANDOFF" ]]; then
  # No handoff doc — quietly exit. Claude must create it on next iteration.
  exit 0
fi

TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Pull current state from gsd-tools (best-effort, tool may be missing in transient envs)
STATE_LINE=$(grep -E '^(status|stopped_at|last_activity)' "$REPO/.planning/STATE.md" 2>/dev/null | tr '\n' '|' | sed 's/|$//' || echo "state unavailable")

# Last commit summary
LAST_COMMIT=$(cd "$REPO" && git log --oneline -1 2>/dev/null || echo "no-git")

# Iteration counter from ralph-loop.local.md
ITER=$(grep -E '^iteration:' "$RALPH_STATUS" 2>/dev/null | awk '{print $2}' || echo "?")

# Append a single line to the History section. Use awk to insert before EOF.
ENTRY="- $TS — stop-hook iter=$ITER state=[$STATE_LINE] last_commit=[$LAST_COMMIT]"

# Append to file (idempotent — just adds a line each time)
echo "$ENTRY" >> "$HANDOFF"

# Output JSON to inform the user the hook fired (small confirmation).
cat <<EOF
{"systemMessage": "ralph-stop-hook: snapshot logged to RALPH-HANDOFF.md (iter=$ITER)"}
EOF

exit 0
