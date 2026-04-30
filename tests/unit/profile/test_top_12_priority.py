"""TRANS-01..05 / D-20..D-22 — top-12 association map asserted against classifier."""
from __future__ import annotations

from pathlib import Path

import pytest

from cua_overlay.profile.classifier import classify
from cua_overlay.profile.known_apps import KNOWN_APPS


pytestmark = pytest.mark.asyncio


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override the disk cache to tmp_path so tests don't pollute ~/.cua/profiles."""
    monkeypatch.setattr(
        "cua_overlay.profile.classifier._CACHE_DIR_OVERRIDE", tmp_path
    )
    return tmp_path


@pytest.fixture
def fake_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub probe_bundle_metadata so tests don't require the actual app installed.
    Returns a fixed metadata payload with bundle_version <= every min_known_version."""

    async def _fake(bundle_id: str) -> dict:
        return {
            "bundle_version": "13.0",
            "bundle_build": "1.0",
            "bundle_path": f"/Applications/{bundle_id}.app",
            "info_plist": {},
        }

    monkeypatch.setattr(
        "cua_overlay.profile.classifier.probe_bundle_metadata", _fake
    )


@pytest.fixture
def fake_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the AX/CDP/AppleScript probes so tests don't require live macOS apps."""

    async def _ax_rich(pid: int) -> bool:
        return False

    async def _ax_observer(pid: int) -> bool:
        return False

    async def _cdp(pid: int):
        return None

    monkeypatch.setattr("cua_overlay.profile.classifier.probe_ax_rich", _ax_rich)
    monkeypatch.setattr(
        "cua_overlay.profile.classifier.probe_ax_observer_works", _ax_observer
    )
    monkeypatch.setattr("cua_overlay.profile.classifier.probe_cdp_ports", _cdp)
    monkeypatch.setattr(
        "cua_overlay.profile.classifier.probe_electron",
        lambda path: False,
    )
    monkeypatch.setattr(
        "cua_overlay.profile.classifier.probe_applescript_sdef",
        lambda info_plist: False,
    )
    monkeypatch.setattr(
        "cua_overlay.profile.classifier.probe_tauri_or_wails",
        lambda path, info_plist: False,
    )


@pytest.fixture
def fake_tcc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub TCC monitor to always return True (granted).

    Patches the TCCMonitor.check class method (NOT the module-level _tcc
    instance attribute) so that monkeypatch's teardown cleanly restores the
    original method. Patching the instance creates a shadowing instance
    attribute that monkeypatch cannot restore correctly, which leaks into
    sibling tests (test_tcc.py::test_classify_calls_tcc_check_at_start).
    """
    from cua_overlay.profile.tcc import TCCMonitor

    async def _granted(self) -> bool:
        return True

    monkeypatch.setattr(TCCMonitor, "check", _granted)


@pytest.fixture
def stubbed_classify(fake_meta, fake_probes, fake_tcc, tmp_cache):
    """Compose all probe stubs."""
    yield


async def test_calculator_uses_bundled_priority(stubbed_classify) -> None:
    profile = await classify("com.apple.calculator", 1234)
    assert profile.translator_priority == ["T1", "T4"]


async def test_slack_flags_cdp_after_relaunch(stubbed_classify) -> None:
    profile = await classify("com.tinyspeck.slackmacgap", 1234)
    assert profile.cdp_available_after_relaunch is True
    assert profile.translator_priority == ["T2", "T4", "T5"]


async def test_pages_priority_t3_first(stubbed_classify) -> None:
    profile = await classify("com.apple.iWork.Pages", 1234)
    assert profile.translator_priority == ["T3", "T1", "T4"]


async def test_chess_priority_t4_t5(stubbed_classify) -> None:
    profile = await classify("com.apple.Chess", 1234)
    assert profile.translator_priority == ["T4", "T5"]


async def test_cursor_obsidian_cdp_flagged(stubbed_classify) -> None:
    p_cursor = await classify("com.todesktop.230313mzl4w4u92", 1234)
    p_obsidian = await classify("md.obsidian", 1234)
    assert p_cursor.cdp_available_after_relaunch is True
    assert p_obsidian.cdp_available_after_relaunch is True


async def test_unknown_bundle_falls_through(stubbed_classify) -> None:
    """D-23: unknown bundles fall through to live-probe derivation."""
    profile = await classify("com.unknown.NotInMap", 1234)
    # Live-probe path returns the Phase 1 default (T4, T5 tail; T1 not added
    # because ax_rich is stubbed False; T3 not added because sdef False).
    assert profile.translator_priority == ["T4", "T5"]


async def test_pages_version_drift_warning(stubbed_classify, monkeypatch) -> None:
    """D-20 drift detection: live bundle_version newer than min_known_version
    triggers fallthrough + structlog warning."""

    async def _new_meta(bundle_id: str) -> dict:
        return {
            "bundle_version": "15.0",  # newer than KNOWN_APPS["com.apple.iWork.Pages"].min_known_version="14.0"
            "bundle_build": "1.0",
            "bundle_path": "/Applications/Pages.app",
            "info_plist": {},
        }

    monkeypatch.setattr(
        "cua_overlay.profile.classifier.probe_bundle_metadata", _new_meta
    )
    profile = await classify("com.apple.iWork.Pages", 1234)
    # Fell through to live derivation; bundled priority NOT applied.
    # With ax_rich=False, sdef=False, electron=False — falls to T4/T5 tail.
    assert profile.translator_priority == ["T4", "T5"]


async def test_top_12_all_present_in_known_apps() -> None:
    """All 12 D-21 bundleIDs are present in KNOWN_APPS, plus 5 D-22 bonus = 17 total."""
    expected_top_12 = {
        "com.apple.calculator", "com.apple.iWork.Pages", "com.apple.iWork.Numbers",
        "com.apple.iWork.Keynote", "com.apple.mail", "com.apple.iCal",
        "com.apple.Notes", "com.apple.reminders", "com.apple.Safari",
        "com.tinyspeck.slackmacgap", "com.todesktop.230313mzl4w4u92", "md.obsidian",
    }
    assert expected_top_12.issubset(KNOWN_APPS.keys())
    assert len(KNOWN_APPS) == 17
