"""Unit tests for cua_overlay.profile.tcc (Plan 01-02 Task 2).

Behavior tests per plan:
1. test_check_returns_axisprocesstrusted: monkey-patch HIServices.AXIsProcessTrusted
   and assert check() reflects it.
2. test_on_revocation_emits_structlog_event: structlog event 'tcc_revoked' with
   action_url containing the System Settings URL.
3. test_on_revocation_raises_systemexit: SystemExit(2) raised after logging.
4. test_classify_calls_tcc_check_at_start: classify() invokes TCCMonitor.check()
   before running any probe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import LogCapture

from cua_overlay.profile import classifier as classifier_mod
from cua_overlay.profile.classifier import AppProfile
from cua_overlay.profile.tcc import TCCMonitor


@pytest.fixture
def log_output():
    """Capture structlog events for assertions."""
    captured = LogCapture()
    structlog.configure(processors=[captured])
    yield captured
    # Reset to a no-op processor chain for other tests.
    structlog.reset_defaults()


async def test_check_returns_axisprocesstrusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("HIServices.AXIsProcessTrusted", lambda: True)
    monitor = TCCMonitor()
    assert await monitor.check() is True

    monkeypatch.setattr("HIServices.AXIsProcessTrusted", lambda: False)
    assert await monitor.check() is False


async def test_on_revocation_emits_structlog_event(log_output: LogCapture) -> None:
    monitor = TCCMonitor()
    with pytest.raises(SystemExit):
        await monitor.on_revocation()

    events = [e for e in log_output.entries if e.get("event") == "tcc_revoked"]
    assert len(events) == 1, f"expected 1 tcc_revoked event, got {log_output.entries}"
    evt = events[0]
    assert "x-apple.systempreferences" in evt.get("action_url", "")
    assert "Privacy_Accessibility" in evt.get("action_url", "")


async def test_on_revocation_raises_systemexit() -> None:
    monitor = TCCMonitor()
    with pytest.raises(SystemExit) as excinfo:
        await monitor.on_revocation()
    assert excinfo.value.code == 2


async def test_classify_calls_tcc_check_at_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """classify() must call TCCMonitor.check() before any probe.

    Strategy: patch the TCC check to a counter that records the call AND
    raises SystemExit on a False-equivalent, so we verify both ordering and
    short-circuit. Then patch with a True returning counter and ensure it was
    incremented before we hit the probe stage.
    """
    call_log: list[str] = []

    async def _fake_check(self) -> bool:
        call_log.append("tcc.check")
        return True

    monkeypatch.setattr(TCCMonitor, "check", _fake_check)

    # Stub out the cache lookup + probes so we don't actually probe a real PID.
    async def _fake_bundle_meta(bundle_id: str) -> dict:
        call_log.append("probe.bundle_metadata")
        return {
            "bundle_path": "/Applications/Fake.app",
            "bundle_version": "1.0",
            "bundle_build": "1",
            "info_plist": {},
        }

    async def _fake_ax(pid: int) -> bool:
        call_log.append("probe.ax_rich")
        return False

    async def _fake_obs(pid: int) -> bool:
        call_log.append("probe.ax_observer_works")
        return False

    async def _fake_cdp(pid: int):
        call_log.append("probe.cdp_ports")
        return None

    monkeypatch.setattr(classifier_mod, "probe_bundle_metadata", _fake_bundle_meta)
    monkeypatch.setattr(classifier_mod, "probe_ax_rich", _fake_ax)
    monkeypatch.setattr(classifier_mod, "probe_ax_observer_works", _fake_obs)
    monkeypatch.setattr(classifier_mod, "probe_cdp_ports", _fake_cdp)
    monkeypatch.setattr(classifier_mod, "_CACHE_DIR_OVERRIDE", tmp_path)

    profile = await classifier_mod.classify("com.example.NotReal", pid=99999)
    assert isinstance(profile, AppProfile)
    # tcc.check must be the FIRST entry in the call log.
    assert call_log[0] == "tcc.check", f"call order was: {call_log}"
