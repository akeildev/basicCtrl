"""Wave 0 scaffold tests.

Verifies the cua_overlay package + libs/cua-driver vendoring + pytest
asyncio_mode=auto are all wired correctly. No real Mac integration here.
"""
from __future__ import annotations

from pathlib import Path


def test_package_imports() -> None:
    """cua_overlay and cua_overlay.state must import without raising."""
    import cua_overlay  # noqa: F401
    import cua_overlay.state  # noqa: F401

    assert hasattr(cua_overlay, "__version__")
    assert isinstance(cua_overlay.__version__, str)


def test_pyobjc_importable() -> None:
    """AXIsProcessTrusted must resolve via HIServices or ApplicationServices.

    pyobjc 12.1 may export the symbol from either framework wrapper depending
    on how the vendor packaged it on macOS 26. We accept either.
    """
    try:
        from HIServices import AXIsProcessTrusted  # type: ignore[attr-defined]
    except ImportError:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore[attr-defined]

    # Don't actually call it (would prompt TCC); just confirm the symbol exists.
    assert callable(AXIsProcessTrusted)


def test_libs_cua_driver_present() -> None:
    """libs/cua-driver/ must be vendored at repo root (NOT a submodule).

    Vendoring (rather than git submodule) is intentional: keeps the trycua
    Swift source read-only and makes rebases an explicit, audited action.
    """
    repo_root = _repo_root()
    driver_dir = repo_root / "libs" / "cua-driver"
    assert driver_dir.is_dir(), f"libs/cua-driver/ missing at {driver_dir}"

    sources = driver_dir / "Sources"
    assert sources.is_dir(), "libs/cua-driver/Sources/ missing — vendoring incomplete"

    tool_registry = sources / "CuaDriverServer" / "ToolRegistry.swift"
    assert tool_registry.is_file(), (
        "ToolRegistry.swift missing — Plan 08 (MCP hook) cannot wire post-action callback"
    )


async def test_pytest_asyncio_auto_mode() -> None:
    """An `async def test_x` runs without @pytest.mark.asyncio (auto-mode)."""
    assert True


def _repo_root() -> Path:
    """Walk up from this test file until we find pyproject.toml."""
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise AssertionError(
        "Could not locate repo root (no pyproject.toml found in any parent)"
    )
