"""AppProfile disk cache: ~/.cua/profiles/<bundle_id>.json.

Atomic write per Pitfall 16 (avoid torn writes on crash). Cache invalidation
keyed on (bundle_version, bundle_build) so a re-probe is forced after an app
upgrade.

Tests pass `base=tmp_path` to override the real ~/.cua/profiles/ directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from basicctrl.profile.classifier import AppProfile

_CACHE_DIR = Path.home() / ".cua" / "profiles"


def _cache_path(bundle_id: str, base: Optional[Path] = None) -> Path:
    """Return the on-disk cache file path for bundle_id.

    The filename is <bundle_id>.json — version is NOT in the path so re-probes
    of the same bundle (after upgrade) overwrite a single cache entry.
    """
    d = base if base is not None else _CACHE_DIR
    return d / f"{bundle_id}.json"


def save_cached_profile(profile: AppProfile, base: Optional[Path] = None) -> Path:
    """Atomic write of profile to disk. Returns the final path.

    Writes to <path>.tmp then os.replace — survives crash without torn-write
    file (Pitfall 16 mitigation).
    """
    path = _cache_path(profile.bundle_id, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(profile.model_dump_json(indent=2))
    os.replace(tmp, path)
    return path


def load_cached_profile(
    bundle_id: str, base: Optional[Path] = None
) -> Optional["AppProfile"]:
    """Load AppProfile from disk; None if missing or corrupt."""
    # Lazy import to avoid circular dependency: classifier imports this module.
    from basicctrl.profile.classifier import AppProfile

    path = _cache_path(bundle_id, base)
    if not path.exists():
        return None
    try:
        return AppProfile.model_validate_json(path.read_text())
    except Exception:
        # Corrupt cache file: re-probe.
        return None


def should_invalidate_cache(
    cached: AppProfile,
    current_bundle_version: Optional[str],
    current_bundle_build: Optional[str],
) -> bool:
    """Return True iff bundle_version OR bundle_build differs from cached.

    Pitfall 16 mitigation: schema/version drift breaks reads; force re-probe
    when the bundle changes underneath us.
    """
    if cached.bundle_version != current_bundle_version:
        return True
    if cached.bundle_build != current_bundle_build:
        return True
    return False
