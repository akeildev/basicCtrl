"""Electron CDP attach + launch helpers.

Electron is Chromium under the hood. Every Electron app accepts
``--remote-debugging-port=NNNN`` at launch. This module:

- Knows which macOS bundle IDs are Electron apps (extensible).
- Resolves bundle_id → app name (via osascript lookup, with built-in
  defaults for common apps).
- Launches an app with the CDP flag via ``open -a <App> --args
  --remote-debugging-port=<port>``.
- Probes ``http://127.0.0.1:<port>/json/version`` until live.
- Picks a free port from a range, deterministic per bundle_id so
  re-launches reuse the same port.

The actual CDP transport is daemon.py + helpers.py — protocol-agnostic.
This module only handles the launch + discovery layer.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


# Known Electron apps on macOS. App name is what `open -a` accepts.
# Default port is deterministic so the same app always gets the same
# slot across daemon restarts. Users can override at launch time.
KNOWN_ELECTRON_APPS: dict[str, dict[str, object]] = {
    "com.tinyspeck.slackmacgap":      {"name": "Slack",                "port": 9222},
    "com.hnc.Discord":                {"name": "Discord",              "port": 9223},
    "com.microsoft.VSCode":           {"name": "Visual Studio Code",   "port": 9224},
    "com.todesktop.230313mzl4w4u92":  {"name": "Cursor",               "port": 9225},
    "com.linear":                     {"name": "Linear",               "port": 9226},
    "com.figma.Desktop":              {"name": "Figma",                "port": 9227},
    "com.spotify.client":             {"name": "Spotify",              "port": 9228},
    "md.obsidian":                    {"name": "Obsidian",             "port": 9229},
    "com.github.GitHubClient":        {"name": "GitHub Desktop",       "port": 9230},
    "notion.id":                      {"name": "Notion",               "port": 9231},
    "com.microsoft.teams2":           {"name": "Microsoft Teams",      "port": 9232},
    "com.todoist.mac.Todoist":        {"name": "Todoist",              "port": 9233},
    "org.whispersystems.signal-desktop": {"name": "Signal",            "port": 9234},
    "com.postmanlabs.mac":            {"name": "Postman",              "port": 9235},
}

# Port scan range for unknown apps + collision fallback.
PORT_RANGE_START = 9240
PORT_RANGE_END = 9299


def is_electron_app(bundle_id: str) -> bool:
    """True if the bundle_id is a known Electron app.

    Unknown bundle IDs return False — caller should explicitly opt in
    via ``launch(bundle_id, app_name=...)`` if they know it's Electron
    but it's not in the registry.
    """
    return bundle_id in KNOWN_ELECTRON_APPS


def app_name_for(bundle_id: str) -> Optional[str]:
    """Lookup app name for ``open -a``. Falls back to osascript."""
    if entry := KNOWN_ELECTRON_APPS.get(bundle_id):
        return str(entry["name"])
    try:
        out = subprocess.run(
            ["osascript", "-e", f'tell application "Finder" to get name of (POSIX file "/Applications") as text'],
            capture_output=True, text=True, timeout=5,
        )
        # Best-effort. The simple fallback below covers most cases.
    except Exception:
        pass
    # Fallback: try `mdfind` to locate the .app bundle by ID.
    try:
        out = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
            capture_output=True, text=True, timeout=5,
        )
        first = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
        if first.endswith(".app"):
            return Path(first).stem
    except Exception:
        pass
    return None


def default_port_for(bundle_id: str) -> int:
    """Deterministic default port for a bundle_id. Known apps use the
    registry value; unknown apps hash into PORT_RANGE_START..END."""
    if entry := KNOWN_ELECTRON_APPS.get(bundle_id):
        return int(entry["port"])
    h = int(hashlib.sha1(bundle_id.encode()).hexdigest(), 16)
    span = PORT_RANGE_END - PORT_RANGE_START + 1
    return PORT_RANGE_START + (h % span)


def is_port_listening(port: int, timeout: float = 0.3) -> bool:
    """Cheap TCP probe — does anything bind to 127.0.0.1:port?"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def is_cdp_alive(port: int, timeout: float = 1.0) -> bool:
    """Stronger check: does /json/version respond with a CDP payload?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            data = json.loads(r.read())
            return "webSocketDebuggerUrl" in data
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return False


def cdp_ws_url(port: int, timeout: float = 2.0) -> Optional[str]:
    """Resolve the CDP WebSocket URL for a port. Returns None if dead."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.loads(r.read())["webSocketDebuggerUrl"]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def app_is_running(app_name: str) -> bool:
    """Check if a macOS app is currently running."""
    try:
        out = subprocess.run(
            ["osascript", "-e", f'application "{app_name}" is running'],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip().lower() == "true"
    except Exception:
        return False


def launch(
    bundle_id: str,
    port: Optional[int] = None,
    app_name: Optional[str] = None,
    quit_first: bool = False,
    wait_seconds: float = 15.0,
) -> dict[str, object]:
    """Launch an Electron app with --remote-debugging-port.

    Returns ``{"ok": True, "port": int, "ws_url": str, "app": str}`` on
    success, ``{"ok": False, "error": str, "hint": str}`` on failure.

    Self-heal levels:
    - L5 (port collision): if requested port is in use AND it's not OUR
      CDP, falls through to next port in PORT_RANGE.
    - L3 (already-running-without-CDP): if quit_first=False and the app
      is already running but not exposing CDP on the chosen port,
      returns a clear error suggesting quit_first=True. We do NOT
      auto-quit user sessions silently.
    """
    name = app_name or app_name_for(bundle_id)
    if not name:
        return {
            "ok": False,
            "error": f"unknown app: bundle_id={bundle_id} not in registry and mdfind found no .app",
            "hint": "Pass app_name explicitly, e.g. launch(bundle_id, app_name='Slack')",
        }

    chosen_port = port or default_port_for(bundle_id)

    # If app is already running, decide whether to attach or relaunch.
    if app_is_running(name):
        # Maybe it already has CDP on the chosen port (or any port we know about).
        if is_cdp_alive(chosen_port):
            ws = cdp_ws_url(chosen_port)
            if ws:
                return {"ok": True, "port": chosen_port, "ws_url": ws, "app": name,
                        "note": "already_running_with_cdp"}
        if not quit_first:
            return {
                "ok": False,
                "error": f"{name} is already running without CDP on port {chosen_port}",
                "hint": (
                    f"Quit {name} (or pass quit_first=True) and retry. "
                    "We don't auto-quit because that loses unsaved work / live sessions."
                ),
                "needs_user_action": True,
            }
        # Quit, then fall through to launch.
        try:
            subprocess.run(["osascript", "-e", f'tell application "{name}" to quit'],
                          capture_output=True, timeout=10)
            time.sleep(1.0)
        except Exception:
            pass

    # L5: port collision — if our chosen port is taken by something that
    # isn't CDP, hop to the next free port.
    if is_port_listening(chosen_port) and not is_cdp_alive(chosen_port):
        for alt in range(PORT_RANGE_START, PORT_RANGE_END + 1):
            if not is_port_listening(alt):
                chosen_port = alt
                break
        else:
            return {
                "ok": False,
                "error": f"port {chosen_port} occupied by non-CDP service and no free port in {PORT_RANGE_START}-{PORT_RANGE_END}",
                "hint": "Pass port=<free_port> explicitly.",
            }

    # Launch via `open -a` with the CDP flag.
    try:
        subprocess.Popen(
            ["open", "-na", name, "--args", f"--remote-debugging-port={chosen_port}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        return {"ok": False, "error": f"open -a failed: {exc}",
                "hint": f"Check that '{name}' is installed in /Applications."}

    # L1: poll /json/version with backoff until CDP is live or timeout.
    deadline = time.time() + wait_seconds
    poll = 0.3
    while time.time() < deadline:
        if is_cdp_alive(chosen_port):
            ws = cdp_ws_url(chosen_port)
            if ws:
                return {"ok": True, "port": chosen_port, "ws_url": ws, "app": name,
                        "note": "launched"}
        time.sleep(poll)
        poll = min(poll * 1.3, 1.5)

    return {
        "ok": False,
        "error": f"{name} launched but CDP didn't come up on port {chosen_port} within {wait_seconds}s",
        "hint": (
            "Some apps (Slack with SSO, VS Code with extensions) take longer. "
            "Retry with wait_seconds=30, or check that the app actually opened."
        ),
    }


def find_running_cdp(bundle_id: str, scan_range: bool = True) -> Optional[dict[str, object]]:
    """Look for an already-running CDP endpoint for this app.

    Checks:
    1. The deterministic default port for the bundle_id.
    2. (If scan_range) every port in PORT_RANGE that has live CDP.

    Doesn't verify the CDP is *this* app — caller can confirm via
    /json/list and matching window titles if it matters. Most flows
    just want any CDP they can attach to.
    """
    name = app_name_for(bundle_id)
    if name and not app_is_running(name):
        return None
    chosen = default_port_for(bundle_id)
    if is_cdp_alive(chosen):
        ws = cdp_ws_url(chosen)
        if ws:
            return {"port": chosen, "ws_url": ws, "app": name}
    if not scan_range:
        return None
    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        if is_cdp_alive(port):
            ws = cdp_ws_url(port)
            if ws:
                return {"port": port, "ws_url": ws, "app": name}
    return None


def daemon_name_for(bundle_id: str) -> str:
    """Each Electron app gets its own daemon (so multiple apps can be
    driven simultaneously without target collision). Use a slug derived
    from bundle_id so the daemon name is stable + readable in logs."""
    slug = bundle_id.replace(".", "-").replace("/", "-")
    return f"electron-{slug}"
