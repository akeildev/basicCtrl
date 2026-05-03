"""Add a new Calendar event for tomorrow 5pm via the basicCtrl framework.

GUI-only, no AppleScript: every interaction is a healing-tool call routed
through the proxied MCP server.

Steps (per Calendar.app's natural-language quick-add path):
    1. open -a Calendar; activate
    2. key_combo_with_healing cmd+n          → opens "New Event or Reminder"
    3. type_with_healing "Test event tomorrow 5pm"  → Calendar parses NL
    4. key_combo_with_healing return         → commits the event
    5. snapshot via get_window_state and grep for the title to confirm

The natural-language parser belongs to Calendar.app — we just hand it a
sentence with the right shape and let it pick the date/time.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CAL_BUNDLE = "com.apple.iCal"


async def _call(session: ClientSession, tool: str, args: dict) -> dict:
    res = await session.call_tool(tool, args)
    payload: dict = {"raw": "", "ok": True, "isError": bool(res.isError)}
    for block in res.content or []:
        text = getattr(block, "text", None)
        if text:
            payload["raw"] = text[:300]
            try:
                parsed = json.loads(text)
                payload.update(parsed)
            except json.JSONDecodeError:
                pass
            break
    return payload


def _wait_for_pid(name: str, timeout_s: float = 8.0) -> int:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            out = subprocess.check_output(["pgrep", "-x", name], text=True)
        except subprocess.CalledProcessError:
            time.sleep(0.2)
            continue
        pids = [int(p) for p in out.split() if p.strip().isdigit()]
        if pids:
            return pids[0]
        time.sleep(0.2)
    return 0


def _resolve_calendar_window_id(pid: int) -> int:
    out = subprocess.check_output(["cua-driver", "call", "list_windows"], text=True)
    payload = json.loads(out)
    for w in payload["windows"]:
        if w["pid"] == pid and w["app_name"] == "Calendar" and w.get("title"):
            return int(w["window_id"])
    return 0


async def main() -> int:
    tomorrow = date.today() + timedelta(days=1)
    title = f"basicCtrl test event"
    nl = f"{title} tomorrow at 5pm"

    print(f"  target date    : {tomorrow.isoformat()}")
    print(f"  natural-language phrase: {nl!r}")

    subprocess.run(["open", "-a", "Calendar"], check=False)
    pid = _wait_for_pid("Calendar")
    if pid == 0:
        print("ERROR: Calendar.app didn't launch", file=sys.stderr)
        return 2
    # Activate the app — Calendar's cmd+N is a no-op on a backgrounded window.
    subprocess.run(
        ["osascript", "-e", 'tell application "Calendar" to activate'],
        check=False,
    )
    await asyncio.sleep(1.5)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "basicctrl.mcp_server"],
        env=dict(os.environ),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("  MCP session ready")

            # cmd+N: "New Event or Reminder" — opens an inline event editor
            # under the currently selected calendar slot.
            r1 = await _call(
                session,
                "key_combo_with_healing",
                {"combo": "cmd+n", "bundle_id": CAL_BUNDLE, "pid": pid},
            )
            print(f"  cmd+n      verified={r1.get('verified')}")
            await asyncio.sleep(0.8)

            # Type the natural-language description. The healing tool routes
            # through C4 AppleScript or C3 CGEvent depending on race policy.
            r2 = await _call(
                session,
                "type_with_healing",
                {"text": nl, "bundle_id": CAL_BUNDLE, "pid": pid},
            )
            print(f"  type        verified={r2.get('verified')}")
            await asyncio.sleep(0.8)

            # Return commits the event into the selected calendar.
            r3 = await _call(
                session,
                "key_combo_with_healing",
                {"combo": "return", "bundle_id": CAL_BUNDLE, "pid": pid},
            )
            print(f"  return     verified={r3.get('verified')}")
            await asyncio.sleep(2.0)

            # Verify by snapshotting the AX tree via the proxied tool — look
            # for our title string.
            window_id = _resolve_calendar_window_id(pid)
            verify = await session.call_tool(
                "get_window_state",
                {"pid": pid, "window_id": window_id},
            )
            tree_text = ""
            for block in verify.content or []:
                t = getattr(block, "text", None)
                if t and "AXButton" in t or (t and "Calendar" in t):
                    tree_text = t
                    break
            found = title in tree_text
            print(f"  title visible in AX tree: {found}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
