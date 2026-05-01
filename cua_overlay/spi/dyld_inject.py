"""SPI-06: DYLD injection into Electron renderers (arm64e).

Per RESEARCH.md §"DYLD Injection + arm64e Signing (SPI-06)" L92-131:
- arm64e dylib compilation via clang -arch arm64e
- Code-signed with PAC-aware entitlements (disable-library-validation)
- Injected via DYLD_INSERT_LIBRARIES environment variable
- No SIP partial-off required; standard macOS 26 sufficient

SPIKE OUTCOME (Wave 3, 06-07): GREEN
Per 06-07-SPIKE-OUTCOME.md: arm64e DYLD injection feasible and reliable.
- Dylib loads into Electron helper processes without error
- PAC signature accepted by OS
- Tested on M4 Pro (Slack Helper network process)

PITFALL P19 (BLOCKER): arm64e DYLD signing on Apple Silicon requires:
1. Dylib compiled as arm64e (not universal)
2. Code-signed with PAC-aware entitlements
3. Injected via subprocess.Popen(..., env={DYLD_INSERT_LIBRARIES: path})
"""
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


class DYLDInjectBridge:
    """Wrapper for arm64e DYLD injection into Electron renderers.

    Per ARCHITECTURE.md L8 SPI integration tier:
    "Every SPI has a public-API fallback — no SPIs are gating features."

    Fallback: T1 AX (lossy but functional) if injection unavailable.
    """

    def __init__(self, available: bool = False, dylib_path: Optional[str] = None):
        """
        Args:
            available: Result of probe_dyld_inject() from probe.py
            dylib_path: Path to built cua_inject.dylib (from build.sh or similar)
        """
        self.available = available
        self.dylib_path = dylib_path or self._default_dylib_path()

        if self.available:
            log.info("dyld_inject_bridge_loaded", available=True, dylib_path=self.dylib_path)
        else:
            log.info("dyld_inject_bridge_unavailable", fallback="T1 AX")

    def _default_dylib_path(self) -> str:
        """Return default path to built cua_inject.dylib.

        By convention, built dylib lives in:
        libs/cua-driver/App/spi-dyld/cua_inject.dylib
        """
        import cua_overlay  # type: ignore[import-not-found]

        cua_root = Path(cua_overlay.__file__).parent.parent.parent
        default = cua_root / "libs" / "cua-driver" / "App" / "spi-dyld" / "cua_inject.dylib"
        return str(default)

    async def inject_into_electron_app(
        self, app_path: str, bundle_id: str
    ) -> bool:
        """Inject signed dylib into Electron app via subprocess relaunch.

        Per SPIKE outcome: DYLD_INSERT_LIBRARIES works reliably on arm64e.
        Relaunch required; injection does not apply to already-running processes.

        Args:
            app_path: Path to .app bundle (e.g., "/Applications/Slack.app")
            bundle_id: Bundle identifier (e.g., "com.tinyspeck.slackmacgap")

        Returns:
            True if injection succeeded (subprocess started with DYLD env).
            False if unavailable or injection failed (fallback to T1 AX).
        """
        if not self.available:
            log.warning(
                "dyld_inject_unavailable",
                app_path=app_path,
                bundle_id=bundle_id,
                fallback="T1 AX",
            )
            return False

        # Validate dylib exists
        if not os.path.exists(self.dylib_path):
            log.error(
                "dyld_inject_dylib_not_found",
                dylib_path=self.dylib_path,
                app_path=app_path,
            )
            return False

        try:
            # Build environment with DYLD_INSERT_LIBRARIES
            env = os.environ.copy()
            env["DYLD_INSERT_LIBRARIES"] = self.dylib_path

            # Relaunch the app with injection
            # Note: This is a simplified version. Real usage would check if app
            # is already running, and handle renderer processes specifically.
            proc = await asyncio.to_thread(
                subprocess.Popen,
                [app_path + "/Contents/MacOS/" + self._get_executable(app_path)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            log.info(
                "dyld_inject_launched",
                app_path=app_path,
                bundle_id=bundle_id,
                dylib_path=self.dylib_path,
                pid=proc.pid,
            )
            return True

        except Exception as e:
            log.error(
                "dyld_inject_failed",
                app_path=app_path,
                bundle_id=bundle_id,
                error=str(e),
            )
            return False

    def _get_executable(self, app_path: str) -> str:
        """Extract executable name from .app bundle.

        Reads Info.plist CFBundleExecutable key.

        Args:
            app_path: Path to .app bundle

        Returns:
            Executable name (e.g., "Slack")
        """
        try:
            import plistlib

            plist_path = os.path.join(app_path, "Contents", "Info.plist")
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
            return plist.get("CFBundleExecutable", "executable")
        except Exception:
            # Fallback: assume app name matches bundle basename
            return os.path.basename(app_path).replace(".app", "")

    async def validate_dylib(self) -> bool:
        """Validate that built dylib is arm64e and properly signed.

        Per SPIKE outcome: codesign -v should return "valid on disk".

        Returns:
            True if dylib is valid; False otherwise.
        """
        if not self.available or not os.path.exists(self.dylib_path):
            return False

        try:
            # Check architecture
            result = await asyncio.to_thread(
                subprocess.run,
                ["lipo", "-info", self.dylib_path],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "arm64e" not in result.stdout:
                log.warning("dyld_inject_wrong_architecture", dylib_path=self.dylib_path)
                return False

            # Check code signature
            result = await asyncio.to_thread(
                subprocess.run,
                ["codesign", "-v", "-v", self.dylib_path],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                log.warning(
                    "dyld_inject_signature_invalid",
                    dylib_path=self.dylib_path,
                    error=result.stderr,
                )
                return False

            log.info("dyld_inject_dylib_valid", dylib_path=self.dylib_path)
            return True

        except Exception as e:
            log.error(
                "dyld_inject_validation_failed",
                dylib_path=self.dylib_path,
                error=str(e),
            )
            return False


# Module-level singleton initialized once at session start
_bridge: Optional[DYLDInjectBridge] = None


async def get_dyld_inject_bridge(capabilities) -> DYLDInjectBridge:
    """Get or initialize DYLD injection bridge.

    Per RESEARCH.md Capability Probe Pattern L181-217:
    "Every SPI needs a probe that runs at session start and caches the result."

    Args:
        capabilities: SPICapabilities from phase 6 Wave 0 probe

    Returns:
        DYLDInjectBridge instance (always returns, fallback graceful)
    """
    global _bridge
    if _bridge is None:
        _bridge = DYLDInjectBridge(available=capabilities.dyld_inject_available)
    return _bridge


async def is_dyld_inject_available(capabilities) -> bool:
    """Check if DYLD injection is available on this system.

    Used by channel_registry to gate C2_DYLDRenderer channel registration.
    """
    bridge = await get_dyld_inject_bridge(capabilities)
    return bridge.available
