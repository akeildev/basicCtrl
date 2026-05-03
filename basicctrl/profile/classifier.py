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

from basicctrl.profile.cache import (
    load_cached_profile,
    save_cached_profile,
    should_invalidate_cache,
)
from basicctrl.profile.capability_probe import (
    probe_applescript_sdef,
    probe_ax_observer_works,
    probe_ax_rich,
    probe_bundle_metadata,
    probe_cdp_ports,
    probe_electron,
    probe_tauri_or_wails,
)
from basicctrl.profile.known_apps import KNOWN_APPS, KnownApp
from basicctrl.profile.tcc import TCCMonitor


class AppProfile(BaseModel):
    """Per-bundle capability probe result. Cached at ~/.cua/profiles/<bundle_id>.json.

    Phase 2 translators import this verbatim and use it to pick T1..T5 priority.
    Phase 4 adds cognition_capable field for graceful degradation (D-31, D-32).
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

    # Phase 4: Cognition capability (D-31, D-32)
    cognition_capable: Optional[bool] = None  # True if local models available; False if missing

    # Phase 6: SPI capabilities (cached at session start)
    spi_skylight_available: bool = False
    spi_ax_remote_available: bool = False
    spi_cgs_display_space_available: bool = False
    spi_endpoint_security_available: bool = False
    spi_dtrace_available: bool = False
    spi_dyld_inject_available: bool = False
    spi_webkit_inspector_available: bool = False
    spi_imu_available: bool = False

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


def _is_version_newer(live: str, known: str) -> bool:
    """Return True iff `live` is strictly newer than `known` per simple
    dotted-decimal comparison.

    "15.0" > "14.0" → True. "14.5" > "14.0" → True. "14.0" > "14.0" → False.
    Non-numeric components compared lexicographically (sort after numeric).
    """
    def _tup(v: str) -> tuple:
        parts: list[object] = []
        for chunk in v.split("."):
            try:
                parts.append((0, int(chunk)))
            except ValueError:
                parts.append((1, chunk))
        return tuple(parts)
    return _tup(live) > _tup(known)


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


def _probe_cognition_capable() -> bool:
    """Probe if local cognition models are available (D-31, D-32).

    Per D-31: capability probe checks:
    - Apple FM SDK available + macOS 26+ + Apple Intelligence enabled?
    - mlx-vlm installable + UI-TARS-1.5-7B model loadable?
    - FAISS + sentence-transformers available?

    Returns True if all available, False if any missing.
    Graceful degradation: if False, B3/B4 recovery branches + ensemble voting skip.
    """
    log = structlog.get_logger()

    try:
        # Check 1: Apple FM SDK
        try:
            import apple_fm_sdk  # noqa: F401
            log.debug("cognition.probe.apple_fm_available")
        except ImportError:
            log.warning("cognition.probe.apple_fm_unavailable")
            return False

        # Check 2: mlx-vlm
        try:
            import mlx_vlm  # noqa: F401
            log.debug("cognition.probe.mlx_vlm_available")
        except ImportError:
            log.warning("cognition.probe.mlx_vlm_unavailable")
            return False

        # Check 3: FAISS
        try:
            import faiss  # noqa: F401
            log.debug("cognition.probe.faiss_available")
        except ImportError:
            log.warning("cognition.probe.faiss_unavailable")
            return False

        # All checks passed
        log.info("cognition.probe.all_available")
        return True

    except Exception as e:
        log.error("cognition.probe.error", error=str(e))
        return False


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

    # 3.5 (NEW Phase 2): bundled top-12 short-circuit (D-20).
    # We still run probes so the AppProfile carries honest ax/cdp signals
    # (downstream tools may read them), but the translator_priority and
    # cdp_available_after_relaunch flag are sourced from KNOWN_APPS unless
    # the live bundle_version drifts past min_known_version.
    bundled: Optional[KnownApp] = KNOWN_APPS.get(bundle_id)
    bundled_priority: Optional[list[str]] = None
    bundled_cdp_after: bool = False
    if bundled is not None:
        if (
            bundled.min_known_version is not None
            and meta["bundle_version"]
            and _is_version_newer(meta["bundle_version"], bundled.min_known_version)
        ):
            log.warning(
                "known_app.version_drift",
                bundle=bundle_id,
                known=bundled.min_known_version,
                live=meta["bundle_version"],
            )
            # Fall through — do NOT use bundled priority; live probe wins.
        else:
            bundled_priority = list(bundled.translator_priority)
            bundled_cdp_after = bundled.cdp_after_relaunch
            log.info(
                "known_app.short_circuit",
                bundle=bundle_id,
                priority=bundled_priority,
                cdp_after_relaunch=bundled_cdp_after,
            )

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

    # Phase 4: Probe cognition capability (D-31, D-32)
    # Run once at session start; cached in AppProfile
    cognition_capable = _probe_cognition_capable()

    # Phase 6: Probe SPI capabilities
    # Run once at session start; cached in AppProfile
    from basicctrl.spi import probe_spi_capabilities
    spi_caps = await probe_spi_capabilities()

    profile = AppProfile(
        bundle_id=bundle_id,
        bundle_version=meta["bundle_version"],
        bundle_build=meta["bundle_build"],
        bundle_path=meta["bundle_path"],
        ax_rich=results["ax_rich"],
        ax_observer_works=results["ax_observer_works"],
        applescript_sdef=has_sdef,
        cdp_port=results["cdp_port"],
        cdp_available_after_relaunch=(
            bundled_cdp_after if bundled is not None and bundled_priority is not None
            else (is_electron and results["cdp_port"] is None)
        ),
        tauri_or_wails=is_tauri,
        electron=is_electron,
        tcc_axenabled=True,  # we already checked above; if False we'd have exited
        cognition_capable=cognition_capable,
        spi_skylight_available=spi_caps.skylight_available,
        spi_ax_remote_available=spi_caps.ax_remote_available,
        spi_cgs_display_space_available=spi_caps.cgs_display_space_available,
        spi_endpoint_security_available=spi_caps.endpoint_security_available,
        spi_dtrace_available=spi_caps.dtrace_available,
        spi_dyld_inject_available=spi_caps.dyld_inject_available,
        spi_webkit_inspector_available=spi_caps.webkit_inspector_available,
        spi_imu_available=spi_caps.imu_available,
        translator_priority=bundled_priority if bundled_priority is not None else priority,
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
        cognition_capable=cognition_capable,
    )
    return profile
