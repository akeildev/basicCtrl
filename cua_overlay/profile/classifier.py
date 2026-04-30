"""AppProfile Pydantic model + classify(bundle_id, pid) entry-point.

The schema is the canonical contract Phase 2 translators import verbatim —
DO NOT redefine elsewhere.

classify() runs all per-capability probes IN PARALLEL via anyio.create_task_group
with a 200ms timeout per probe (handled inside each probe). TCC is checked
FIRST, before any probe runs — Pitfall 24 mitigation.

Cache layer: ~/.cua/profiles/<bundle_id>.json. First probe <500ms; cached
re-probe <5ms.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anyio
import structlog
from pydantic import BaseModel, Field

from cua_overlay.profile.cache import (
    load_cached_profile,
    save_cached_profile,
    should_invalidate_cache,
)
from cua_overlay.profile.capability_probe import (
    probe_applescript_sdef,
    probe_ax_observer_works,
    probe_ax_rich,
    probe_bundle_metadata,
    probe_cdp_ports,
    probe_electron,
    probe_tauri_or_wails,
)
from cua_overlay.profile.tcc import TCCMonitor


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


# Module-level TCC monitor instance. Re-checked at every classify() call
# (Pitfall 24 — TCC is mutable runtime user state).
_tcc = TCCMonitor()

# Test override hook: when set (by tests via monkeypatch), the cache reads/writes
# go to this directory instead of ~/.cua/profiles/. Production code never sets
# this.
_CACHE_DIR_OVERRIDE: Optional[Path] = None


def _derive_translator_priority(
    *,
    is_electron: bool,
    cdp_port: Optional[int],
    ax_rich: bool,
    has_sdef: bool,
) -> list[str]:
    """Compose the translator priority list deterministically.

    Order rules:
    - T2 CDP first when Electron AND CDP port reachable (richest DOM access).
    - T1 AX next when ax_rich (sub-1ms push events).
    - T3 AppleScript next when .sdef present (semantic verbs).
    - T4 Vision/OCR + T5 Pixel always at the tail (universal fallbacks).
    """
    priority: list[str] = []
    if is_electron and cdp_port is not None:
        priority.append("T2")
    if ax_rich:
        priority.append("T1")
    if has_sdef:
        priority.append("T3")
    priority.append("T4")
    priority.append("T5")
    return priority


async def classify(bundle_id: str, pid: int) -> AppProfile:
    """Classify a running Mac app by capability probe.

    Returns a cached AppProfile when (bundle_version, bundle_build) match the
    on-disk record; otherwise runs all probes in parallel (anyio task group)
    and writes a fresh cache entry.

    First probe: <500ms total. Cached re-probe: <5ms.

    Pitfall 24: TCC is checked at the very first line. On revocation we emit
    a structlog event and SystemExit(2) (Phase 1 hard fail; Phase 5 swaps in
    NSPanel prompt).
    """
    t_start = time.monotonic()
    log = structlog.get_logger().bind(bundle_id=bundle_id, pid=pid)

    # Pitfall 24 mitigation: TCC check at every classify() entry point.
    if not await _tcc.check():
        await _tcc.on_revocation()  # raises SystemExit(2)

    # FAST PATH: bundle metadata first (~5ms sync), then check disk cache.
    meta = await probe_bundle_metadata(bundle_id)
    cache_base = _CACHE_DIR_OVERRIDE
    cached = load_cached_profile(bundle_id, base=cache_base)
    if cached and not should_invalidate_cache(
        cached, meta["bundle_version"], meta["bundle_build"]
    ):
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        log.info("appprofile_cache_hit", elapsed_ms=elapsed_ms)
        return cached

    # PARALLEL PROBES via anyio task group. Each probe self-caps at 200ms
    # (or 500ms for the AXObserver probe per Pitfall 14 budget).
    is_electron = probe_electron(meta["bundle_path"])
    results: dict = {"ax_rich": False, "ax_observer_works": False, "cdp_port": None}

    async def _ax_rich_task() -> None:
        results["ax_rich"] = await probe_ax_rich(pid)

    async def _ax_observer_task() -> None:
        results["ax_observer_works"] = await probe_ax_observer_works(pid)

    async def _cdp_task() -> None:
        # CDP probing is only meaningful for Electron bundles.
        if is_electron:
            results["cdp_port"] = await probe_cdp_ports(pid)
        else:
            results["cdp_port"] = None

    async with anyio.create_task_group() as tg:
        tg.start_soon(_ax_rich_task)
        tg.start_soon(_ax_observer_task)
        tg.start_soon(_cdp_task)

    has_sdef = probe_applescript_sdef(meta["info_plist"])
    is_tauri = probe_tauri_or_wails(meta["bundle_path"], meta["info_plist"])
    if is_tauri:
        log.warning("tauri_or_wails_heuristic_fired", bundle=bundle_id)

    priority = _derive_translator_priority(
        is_electron=is_electron,
        cdp_port=results["cdp_port"],
        ax_rich=results["ax_rich"],
        has_sdef=has_sdef,
    )

    profile = AppProfile(
        bundle_id=bundle_id,
        bundle_version=meta["bundle_version"],
        bundle_build=meta["bundle_build"],
        bundle_path=meta["bundle_path"],
        ax_rich=results["ax_rich"],
        ax_observer_works=results["ax_observer_works"],
        applescript_sdef=has_sdef,
        cdp_port=results["cdp_port"],
        cdp_available_after_relaunch=is_electron and results["cdp_port"] is None,
        tauri_or_wails=is_tauri,
        electron=is_electron,
        tcc_axenabled=True,  # we already checked above; if False we'd have exited
        translator_priority=priority,
        probed_at=datetime.now(timezone.utc),
        probe_latency_ms=int((time.monotonic() - t_start) * 1000),
    )
    save_cached_profile(profile, base=cache_base)
    log.info(
        "appprofile_probed",
        priority=priority,
        latency_ms=profile.probe_latency_ms,
        ax_rich=profile.ax_rich,
        ax_observer_works=profile.ax_observer_works,
        electron=profile.electron,
        cdp_port=profile.cdp_port,
    )
    return profile
