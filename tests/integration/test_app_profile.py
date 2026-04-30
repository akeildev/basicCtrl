"""Integration test: real Calculator launch + AppProfile probe + cache lifecycle.

Plan 01-02 Task 3. Requires:
- Real macOS with Calculator.app at /System/Applications/Calculator.app
- TCC Accessibility granted to the test runner

Skip via SKIP_INTEGRATION=1.

Tests:
1. test_calculator_profile: first-probe returns ax_rich=True, electron=False,
   cdp_port=None, latency<500ms
2. test_cache_persists: second classify() call hits disk cache; latency<5ms
3. test_cache_invalidated_on_version_change: mutated bundle_version forces re-probe
4. test_translator_priority_starts_with_T1_for_calculator: priority[0]=='T1',
   T4+T5 at tail, T2 absent
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cua_overlay.profile import classifier as classifier_mod
from cua_overlay.profile.cache import (
    load_cached_profile,
    save_cached_profile,
)
from cua_overlay.profile.classifier import classify

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_calculator_profile(calculator_pid, tmp_path: Path, monkeypatch) -> None:
    """First probe of Calculator returns expected capabilities within budget."""
    monkeypatch.setattr(classifier_mod, "_CACHE_DIR_OVERRIDE", tmp_path)

    profile = await classify("com.apple.calculator", calculator_pid)

    assert profile.bundle_id == "com.apple.calculator"
    assert profile.ax_rich is True, "Calculator must expose AX children"
    # Calculator is native AppKit, not Electron, no CDP.
    assert profile.electron is False
    assert profile.cdp_port is None
    # ax_observer_works should be True for native AppKit (not Pitfall 14 territory).
    assert profile.ax_observer_works is True, "Calculator native AppKit must support AXObserver"
    # applescript_sdef may be True or False depending on Calculator's Info.plist;
    # don't over-constrain.
    assert isinstance(profile.applescript_sdef, bool)
    # T1 must come first for native AppKit with ax_rich.
    assert profile.translator_priority, "translator_priority must not be empty"
    assert profile.translator_priority[0] == "T1"
    # Latency budget: first probe < 500ms.
    assert profile.probe_latency_ms < 500, (
        f"first-probe latency {profile.probe_latency_ms}ms exceeds 500ms budget"
    )


@pytest.mark.integration
async def test_cache_persists(calculator_pid, tmp_path: Path, monkeypatch) -> None:
    """Second classify() call hits disk cache (<5ms wall clock)."""
    monkeypatch.setattr(classifier_mod, "_CACHE_DIR_OVERRIDE", tmp_path)

    profile1 = await classify("com.apple.calculator", calculator_pid)
    cache_file = tmp_path / "com.apple.calculator.json"
    assert cache_file.exists(), "first classify() must write cache file"

    # Second call: should hit cache.
    t0 = time.monotonic()
    profile2 = await classify("com.apple.calculator", calculator_pid)
    elapsed_ms = (time.monotonic() - t0) * 1000

    # Cache hit: bundle_version + bundle_build identical to original.
    assert profile2.bundle_version == profile1.bundle_version
    assert profile2.bundle_build == profile1.bundle_build
    assert profile2.probed_at == profile1.probed_at, (
        "cache hit must return original profile (same probed_at), got re-probe"
    )
    # Wall-clock budget: cache hit must be <5ms.
    assert elapsed_ms < 5, f"cache-hit latency {elapsed_ms:.2f}ms exceeds 5ms budget"
    # Sanity: probe_latency_ms unchanged on cache hit (it's the original probe's value).
    assert profile2.probe_latency_ms == profile1.probe_latency_ms


@pytest.mark.integration
async def test_cache_invalidated_on_version_change(
    calculator_pid, tmp_path: Path, monkeypatch
) -> None:
    """Mutating cached bundle_version forces a re-probe."""
    monkeypatch.setattr(classifier_mod, "_CACHE_DIR_OVERRIDE", tmp_path)

    profile1 = await classify("com.apple.calculator", calculator_pid)
    # Read cache, mutate version, write back.
    cached = load_cached_profile("com.apple.calculator", base=tmp_path)
    assert cached is not None
    mutated = cached.model_copy(update={"bundle_version": "FAKE_OLD_VERSION"})
    save_cached_profile(mutated, base=tmp_path)

    # Re-classify: should detect mismatch and re-probe (new probed_at).
    profile2 = await classify("com.apple.calculator", calculator_pid)
    assert profile2.bundle_version == profile1.bundle_version, (
        "re-probe must restore real bundle_version (not the mutated FAKE_OLD_VERSION)"
    )
    assert profile2.probed_at >= profile1.probed_at, (
        "re-probe must produce a newer probed_at timestamp"
    )
    # Latency for re-probe should be a real probe (not cache-hit fast).
    # Don't assert lower bound strictly (avoiding flakiness on fast machines);
    # just confirm it's a fresh probe by checking the timestamp moved.
    assert profile2.probe_latency_ms < 500


@pytest.mark.integration
async def test_translator_priority_starts_with_T1_for_calculator(
    calculator_pid, tmp_path: Path, monkeypatch
) -> None:
    """Native AppKit Calculator: T1 first, T4+T5 always, T2 absent."""
    monkeypatch.setattr(classifier_mod, "_CACHE_DIR_OVERRIDE", tmp_path)

    profile = await classify("com.apple.calculator", calculator_pid)
    priority = profile.translator_priority

    assert priority[0] == "T1", f"expected T1 first for AppKit Calculator, got {priority}"
    assert "T4" in priority, "T4 (Vision/OCR) must always be in priority list"
    assert "T5" in priority, "T5 (Pixel) must always be in priority list"
    assert "T2" not in priority, (
        f"Calculator is not Electron — T2 should not appear, got {priority}"
    )
    # T4 and T5 are universal fallbacks: they should be at the tail.
    assert priority[-2:] == ["T4", "T5"], (
        f"T4+T5 must be the final fallbacks, got tail={priority[-2:]}"
    )
