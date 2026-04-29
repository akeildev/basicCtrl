"""AppProfile Pydantic model + classify(bundle_id, pid) entry-point.

Plan 01-02 Task 1: defines the AppProfile schema (Pydantic v2). The schema is
the canonical contract Phase 2 translators import verbatim — DO NOT redefine
elsewhere.

Task 2 fills classify() with the parallel anyio probe + TCC check + cache
read/write.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AppProfile(BaseModel):
    """Per-bundle capability probe result. Cached at ~/.cua/profiles/<bundle_id>.json.

    Phase 2 translators import this verbatim and use it to pick T1..T5 priority.
    """

    bundle_id: str
    bundle_version: Optional[str] = None  # CFBundleShortVersionString
    bundle_build: Optional[str] = None  # CFBundleVersion
    bundle_path: Optional[str] = None  # filesystem path to the .app

    # AX (T1) signals
    ax_rich: bool = False  # AXChildren > 0 within 200ms
    ax_observer_works: bool = False  # AXObserver fires within 500ms (Pitfall 14 detector)

    # AppleScript (T3) signal
    applescript_sdef: bool = False  # Info.plist OSAScriptingDefinition or NSAppleScriptEnabled

    # CDP (T2) signals
    cdp_port: Optional[int] = None  # 9222..9230 reachable, else None
    cdp_available_after_relaunch: bool = False  # is_electron AND cdp_port is None (Pitfall 8)

    # Web-shell heuristics
    tauri_or_wails: bool = False  # WebKit.framework + no .sdef + not Electron (A2 heuristic)
    electron: bool = False  # Electron Framework.framework present

    # TCC
    tcc_axenabled: bool = True  # AXIsProcessTrusted at probe time

    # Derived
    translator_priority: list[str] = Field(default_factory=list)
    probed_at: datetime
    probe_latency_ms: int

    @property
    def cache_key(self) -> str:
        """Composite identity key for in-memory dedupe.

        On-disk file uses bundle_id only (so re-probes overwrite). cache_key
        encodes the version too so two probes of differing versions in the
        same session don't collide in caller dicts.
        """
        return (
            f"{self.bundle_id}@{self.bundle_version or 'unknown'}"
            f"+{self.bundle_build or 'unknown'}"
        )


async def classify(bundle_id: str, pid: int) -> AppProfile:  # pragma: no cover (Task 2 wires this)
    """Classify a running Mac app by capability probe.

    Phase 1 entry-point. Returns a cached AppProfile when (bundle_version,
    bundle_build) match the on-disk record; otherwise runs all probes in
    parallel (anyio task group, 200ms each) and writes a fresh cache entry.

    First probe: <500ms total. Cached re-probe: <5ms.

    Task 2 wires this fully. Task 1 stub.
    """
    raise NotImplementedError("Task 2 wires this")
