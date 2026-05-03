"""Unit tests for basicctrl.profile.cache (Plan 01-02 Task 1).

Behavior tests per plan:
1. test_save_creates_directory: save_cached_profile creates parent dir tree
2. test_atomic_write_uses_replace: writes to .tmp then os.replace, no torn-write file
3. test_load_returns_none_for_missing: missing file returns None (no raise)
4. test_load_returns_appprofile_on_hit: round-trip equality via model_dump
5. test_invalidate_on_version_change: bundle_version differs -> invalidate
6. test_invalidate_on_build_change: bundle_build differs -> invalidate
7. test_no_invalidate_on_same_version_build: identical -> cache hit valid
8. test_cache_path_uses_bundle_id_only: file is <bundle_id>.json (no version segment)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from basicctrl.profile.cache import (
    _cache_path,
    load_cached_profile,
    save_cached_profile,
    should_invalidate_cache,
)
from basicctrl.profile.classifier import AppProfile


def _make_profile(
    bundle_id: str = "com.apple.Calculator",
    bundle_version: str | None = "10.16",
    bundle_build: str | None = "26.4.30.1",
) -> AppProfile:
    return AppProfile(
        bundle_id=bundle_id,
        bundle_version=bundle_version,
        bundle_build=bundle_build,
        bundle_path="/System/Applications/Calculator.app",
        ax_rich=True,
        ax_observer_works=True,
        applescript_sdef=False,
        cdp_port=None,
        cdp_available_after_relaunch=False,
        tauri_or_wails=False,
        electron=False,
        tcc_axenabled=True,
        translator_priority=["T1", "T4", "T5"],
        probed_at=datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc),
        probe_latency_ms=120,
    )


def test_save_creates_directory(tmp_path: Path) -> None:
    base = tmp_path / "deep" / "nested" / "profiles"
    assert not base.exists()
    profile = _make_profile()
    out = save_cached_profile(profile, base=base)
    assert base.exists() and base.is_dir()
    assert out.exists()
    assert out.is_file()


def test_atomic_write_uses_replace(tmp_path: Path) -> None:
    profile = _make_profile()
    out = save_cached_profile(profile, base=tmp_path)
    # No leftover .tmp file
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], f"unexpected .tmp leftover: {leftovers}"
    # Final JSON parses cleanly
    import json

    data = json.loads(out.read_text())
    assert data["bundle_id"] == "com.apple.Calculator"
    assert data["bundle_version"] == "10.16"


def test_load_returns_none_for_missing(tmp_path: Path) -> None:
    result = load_cached_profile("com.example.NotExist", base=tmp_path)
    assert result is None


def test_load_returns_appprofile_on_hit(tmp_path: Path) -> None:
    profile = _make_profile()
    save_cached_profile(profile, base=tmp_path)
    loaded = load_cached_profile("com.apple.Calculator", base=tmp_path)
    assert loaded is not None
    assert loaded.model_dump() == profile.model_dump()


def test_invalidate_on_version_change() -> None:
    cached = _make_profile(bundle_version="10.16", bundle_build="26.4.30.1")
    assert should_invalidate_cache(cached, "10.17", "26.4.30.1") is True


def test_invalidate_on_build_change() -> None:
    cached = _make_profile(bundle_version="10.16", bundle_build="26.4.30.1")
    assert should_invalidate_cache(cached, "10.16", "26.4.31.0") is True


def test_no_invalidate_on_same_version_build() -> None:
    cached = _make_profile(bundle_version="10.16", bundle_build="26.4.30.1")
    assert should_invalidate_cache(cached, "10.16", "26.4.30.1") is False


def test_cache_path_uses_bundle_id_only(tmp_path: Path) -> None:
    profile = _make_profile()
    out = save_cached_profile(profile, base=tmp_path)
    # Path is <bundle_id>.json — no version in filename
    assert out.name == "com.apple.Calculator.json"
    # Confirm helper agrees
    assert _cache_path("com.apple.Calculator", base=tmp_path) == out
    # Re-saving with same bundle_id but different version overwrites the same file
    profile2 = _make_profile(bundle_version="10.99")
    out2 = save_cached_profile(profile2, base=tmp_path)
    assert out2 == out
    files = list(tmp_path.iterdir())
    assert len(files) == 1, f"expected single file, got {files}"
