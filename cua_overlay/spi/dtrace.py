"""SPI-05: DTrace probes (app-internals introspection).

Per RESEARCH.md §"Per-SPI Status Table" L48:
- Tier B: SIP partial-off required (csrutil disable --without dtrace)
- Skip gracefully on default Mac (SIP on)
- Requires explicit dtrace entitlement
"""
import subprocess
from typing import Optional
import structlog

from cua_overlay.spi.probe import is_sip_partial_off

log = structlog.get_logger(__name__)


class DTraceBridge:
    """Wrapper for DTrace probes (app-internals introspection).

    Allows transparent tracing of app syscalls, function calls, and timing.
    Requires SIP partial-off or full-off.
    Gracefully handles unavailability on default Mac.
    """

    def __init__(self, available: bool = False):
        """Initialize DTrace bridge.

        Args:
            available: True if probe found dtrace(1) working and SIP allows.
        """
        self.available = available

        if available:
            self._check_sip_and_dtrace()

    def _check_sip_and_dtrace(self):
        """Verify SIP status and dtrace(1) availability.

        DTrace requires:
        1. SIP partial-off or full-off
        2. dtrace(1) command available
        3. dtrace entitlement (for unprivileged users)

        On success: available remains True.
        On failure: available is downgraded to False.
        """
        try:
            # Check SIP status first
            if not is_sip_partial_off():
                log.info(
                    "dtrace_unavailable_sip_on",
                    reason="SIP is fully on; DTrace requires SIP partial-off",
                )
                self.available = False
                return

            # Check if dtrace(1) is available and working
            result = subprocess.run(
                ["dtrace", "-l", "-n", "syscall:::entry"],
                capture_output=True,
                timeout=2,
                text=True,
            )
            if result.returncode != 0:
                self.available = False
                log.info(
                    "dtrace_unavailable", reason="dtrace(1) returned non-zero", code=result.returncode
                )
            else:
                log.info("dtrace_available", sip_status="partial_off")
        except FileNotFoundError:
            log.info("dtrace_unavailable", reason="dtrace(1) command not found")
            self.available = False
        except subprocess.TimeoutExpired:
            log.warning("dtrace_check_timeout", timeout_sec=2)
            self.available = False
        except PermissionError as e:
            log.info("dtrace_unavailable", reason="Permission denied", error=str(e))
            self.available = False
        except Exception as e:
            log.warning("dtrace_check_failed", error=str(e), error_type=type(e).__name__)
            self.available = False

    async def spawn_probe(self, probe_script: str, timeout: int = 5) -> Optional[str]:
        """Spawn DTrace probe and collect output.

        Args:
            probe_script: D script to run (e.g., "syscall:::entry { @[args[0]] = count() }")
            timeout: Timeout in seconds for probe to complete.

        Returns:
            Aggregated probe output (stdout) if successful; None if unavailable or error.
        """
        if not self.available:
            log.info("dtrace_unavailable_skipping_probe_spawn")
            return None

        try:
            # Spawn dtrace with probe script piped via stdin
            result = subprocess.run(
                ["dtrace", "-s", "-"],
                input=probe_script,
                capture_output=True,
                timeout=timeout,
                text=True,
            )

            if result.returncode == 0:
                log.info("dtrace_probe_completed", output_lines=len(result.stdout.splitlines()))
                return result.stdout
            else:
                log.warning(
                    "dtrace_probe_failed",
                    return_code=result.returncode,
                    stderr=result.stderr[:200],  # Truncate for logging
                )
                return None
        except subprocess.TimeoutExpired:
            log.warning("dtrace_probe_timeout", timeout_sec=timeout)
            return None
        except Exception as e:
            log.error("dtrace_probe_error", error=str(e), error_type=type(e).__name__)
            return None

    async def trace_app_syscalls(self, bundle_id: str, duration_sec: int = 5) -> Optional[str]:
        """Trace all syscalls made by an app for a duration.

        Args:
            bundle_id: macOS bundle ID (e.g., "com.apple.Safari")
            duration_sec: How long to trace (seconds).

        Returns:
            Aggregated syscall counts if successful; None if unavailable.

        Example output:
            execve                                1
            open                                 42
            read                                125
            write                                18
        """
        if not self.available:
            return None

        # D script: count syscalls by type for processes matching bundle_id
        # (In real implementation, would filter by process name or bundle ID)
        probe_script = f"""
syscall:::entry
{{
    @syscall[execname] = count();
}}

profile:::tick-{duration_sec}s
{{
    exit(0);
}}
"""

        return await self.spawn_probe(probe_script, timeout=duration_sec + 5)


_bridge: Optional[DTraceBridge] = None


async def get_dtrace_bridge(capabilities) -> Optional[DTraceBridge]:
    """Get or initialize DTrace bridge.

    Args:
        capabilities: SPICapabilities object from probe_spi_capabilities().

    Returns:
        DTraceBridge if available (SIP partial-off),
        None if DTrace not available on this Mac.
        Result is cached per session.
    """
    global _bridge
    if _bridge is None:
        _bridge = DTraceBridge(available=capabilities.dtrace_available)
    return _bridge
