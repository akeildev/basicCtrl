"""Bundled top-12 app association map (D-20..D-22).

Per CONTEXT.md D-20: classifier consults this BEFORE running capability
probes (cache-miss path) so well-known apps skip ~500ms of probe latency.

Per CONTEXT.md D-21: 12 verified bundleIDs (Calculator, Pages, Numbers,
Keynote, Mail, Calendar, Notes, Reminders, Safari, Slack, Cursor, Obsidian).

Per CONTEXT.md D-22: 5 bonus entries (System Settings, Terminal, Music,
Chrome, Chess).

Per CONTEXT.md D-23: Discord/Notion/Linear NOT in map; fall through to
live probe.

Per CONTEXT.md D-24: Slack/Cursor/Obsidian carry cdp_after_relaunch=True;
the MCP healing tool surface (Plan 02-11) reads AppProfile.cdp_available_after_relaunch
and prompts the user once. Classifier's job is only to set the flag.

bundleIDs verified via local `defaults read` 2026-04-30 (CONTEXT.md D-21).
"""
from __future__ import annotations

from typing import NamedTuple, Optional


class KnownApp(NamedTuple):
    """Bundled per-app association entry."""

    bundle_id: str
    name: str
    electron: bool
    has_sdef: bool
    translator_priority: list[str]
    cdp_after_relaunch: bool  # P8 flag (D-24): Electron app needs --remote-debugging-port relaunch
    min_known_version: Optional[str]  # if live > this, fall through to live probe
    notes: str


KNOWN_APPS: dict[str, KnownApp] = {
    # --- D-21 top-12 ---
    "com.apple.calculator": KnownApp(
        bundle_id="com.apple.calculator",
        name="Calculator",
        electron=False,
        has_sdef=False,
        # T5 (Pixel) is the universal fallback per
        # _derive_translator_priority's contract — must always be present
        # at the tail.
        translator_priority=["T1", "T4", "T5"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="Phase 1 baseline target",
    ),
    "com.apple.iWork.Pages": KnownApp(
        bundle_id="com.apple.iWork.Pages",
        name="Pages",
        electron=False,
        has_sdef=True,
        translator_priority=["T3", "T1", "T4"],
        cdp_after_relaunch=False,
        min_known_version="14.0",
        notes="iWork canvas non-AX; AS for paragraph styles (D-26)",
    ),
    "com.apple.iWork.Numbers": KnownApp(
        bundle_id="com.apple.iWork.Numbers",
        name="Numbers",
        electron=False,
        has_sdef=True,
        translator_priority=["T3", "T1", "T4"],
        cdp_after_relaunch=False,
        min_known_version="14.0",
        notes="Grid via AppleScript",
    ),
    "com.apple.iWork.Keynote": KnownApp(
        bundle_id="com.apple.iWork.Keynote",
        name="Keynote",
        electron=False,
        has_sdef=True,
        translator_priority=["T3", "T1", "T4"],
        cdp_after_relaunch=False,
        min_known_version="14.0",
        notes="Slide canvas non-AX",
    ),
    "com.apple.mail": KnownApp(
        bundle_id="com.apple.mail",
        name="Mail",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3", "T4"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="Toolbar AX-rich",
    ),
    "com.apple.iCal": KnownApp(
        bundle_id="com.apple.iCal",
        name="Calendar",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3", "T4"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="sdef = iCal.sdef",
    ),
    "com.apple.Notes": KnownApp(
        bundle_id="com.apple.Notes",
        name="Notes",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3", "T4"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="",
    ),
    "com.apple.reminders": KnownApp(
        bundle_id="com.apple.reminders",
        name="Reminders",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3", "T4"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="lowercase reminders",
    ),
    "com.apple.Safari": KnownApp(
        bundle_id="com.apple.Safari",
        name="Safari",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="Full AX walk = 15-20s (P3) — depth-3 limit mandatory",
    ),
    "com.tinyspeck.slackmacgap": KnownApp(
        bundle_id="com.tinyspeck.slackmacgap",
        name="Slack",
        electron=True,
        has_sdef=False,
        translator_priority=["T2", "T4", "T5"],
        cdp_after_relaunch=True,
        min_known_version=None,
        notes=(
            "Multi-process renderer; CDP filter type=page AND url~/\\.slack\\.com/ (D-24); "
            "T2 only after manual --remote-debugging-port=9222 relaunch (P8)"
        ),
    ),
    "com.todesktop.230313mzl4w4u92": KnownApp(
        bundle_id="com.todesktop.230313mzl4w4u92",
        name="Cursor",
        electron=True,
        has_sdef=False,
        translator_priority=["T2", "T4", "T5"],
        cdp_after_relaunch=True,
        min_known_version=None,
        notes="todesktop random ID; P8 manual relaunch path",
    ),
    "md.obsidian": KnownApp(
        bundle_id="md.obsidian",
        name="Obsidian",
        electron=True,
        has_sdef=False,
        translator_priority=["T2", "T4", "T5"],
        cdp_after_relaunch=True,
        min_known_version=None,
        notes="P8 manual relaunch path",
    ),
    # --- D-22 bonus entries ---
    "com.apple.systempreferences": KnownApp(
        bundle_id="com.apple.systempreferences",
        name="System Settings",
        electron=False,
        has_sdef=False,
        translator_priority=["T1"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="System Settings — AX-only",
    ),
    "com.apple.Terminal": KnownApp(
        bundle_id="com.apple.Terminal",
        name="Terminal",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="Terminal.sdef present",
    ),
    "com.apple.Music": KnownApp(
        bundle_id="com.apple.Music",
        name="Music",
        electron=False,
        has_sdef=True,
        translator_priority=["T1", "T3"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="com.apple.Music.sdef",
    ),
    "com.google.Chrome": KnownApp(
        bundle_id="com.google.Chrome",
        name="Chrome",
        electron=False,
        has_sdef=False,
        translator_priority=["T2", "T1"],
        cdp_after_relaunch=False,  # Chrome has built-in remote debugging via launch flag
        min_known_version=None,
        notes="Native CDP; not Electron",
    ),
    "com.apple.Chess": KnownApp(
        bundle_id="com.apple.Chess",
        name="Chess",
        electron=False,
        has_sdef=False,
        translator_priority=["T4", "T5"],
        cdp_after_relaunch=False,
        min_known_version=None,
        notes="No .sdef; Metal 3D board; Phase 2 game-canvas test target (D-27)",
    ),
}


def get(bundle_id: str) -> Optional[KnownApp]:
    """Return the bundled KnownApp entry for bundle_id, or None on miss."""
    return KNOWN_APPS.get(bundle_id)
