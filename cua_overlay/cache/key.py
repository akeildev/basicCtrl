"""SHA-256 cache key computation per D-17.

Per CONTEXT.md D-17, the cache key is derived from (bundle_id, role_path, instruction)
as a SHA-256 digest for deterministic, content-addressed cassette storage.
"""
import hashlib


def compute_cache_key(
    bundle_id: str,
    role_path: str,
    instruction: str,
) -> str:
    """Compute SHA-256 cache key per D-17.

    Args:
        bundle_id: e.g., "com.apple.iWork.Pages"
        role_path: e.g., "AXApplication > AXWindow > AXButton"
        instruction: e.g., "click the Format button"

    Returns:
        SHA-256 hex digest (64 chars)
    """
    key_bytes = f"{bundle_id}:{role_path}:{instruction}".encode("utf-8")
    return hashlib.sha256(key_bytes).hexdigest()
