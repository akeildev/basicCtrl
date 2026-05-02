"""structlog NDJSON configuration with contextvar propagation + sensitive-field redaction.

Every Phase-1+ component emits structured events through this configured logger.

Threat T-1-03 mitigation: a custom processor strips fields named in
``_SENSITIVE_FIELDS`` (pasteboard contents, clipboard data, secrets, passwords)
before the JSON renderer sees them. Plan 05's L1 pasteboard signal is allowed
to log the changeCount integer ONLY — not the contents.

Contextvar propagation: structlog.contextvars.merge_contextvars is the first
processor in the chain so a session_id bound via
``structlog.contextvars.bind_contextvars(session_id=...)`` flows across every
asyncio await boundary inside a TaskGroup.
"""
from __future__ import annotations

import sys
from typing import Any, MutableMapping

import structlog
from structlog.contextvars import merge_contextvars

# Field names that must NEVER appear in NDJSON output. Add new ones here as
# downstream phases discover them; removing one requires a security review.
_SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "pasteboard_contents",
        "clipboard_data",
        "secrets",
        "password",
    }
)


def _redact_sensitive(
    _logger: Any,
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """T-1-03: replace sensitive field values with the literal string ``[REDACTED]``.

    We replace, not delete, so downstream consumers can still tell which keys
    were dropped (audit-trail friendly).
    """
    for key in list(event_dict.keys()):
        if key in _SENSITIVE_FIELDS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure(testing: bool = False) -> None:
    """Install the standard processor chain.

    Args:
        testing: when True, append ``structlog.testing.LogCapture`` so tests
            can use ``structlog.testing.capture_logs()`` to assert against
            emitted events. Production code calls ``configure()`` with no
            args at module import time.
    """
    import os

    processors: list[Any] = [
        merge_contextvars,
        _redact_sensitive,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
    ]

    # CUA_DEBUG=1: use DEBUG level and enable TraceBus
    if os.environ.get("CUA_DEBUG") == "1":
        # Add TraceBus processor (best-effort event distribution)
        from cua_overlay.observability.bus import bus_processor
        processors.append(bus_processor)
        log_level = "DEBUG"
    else:
        log_level = "INFO"

    if testing:
        processors.append(structlog.processors.dict_tracebacks)
        processors.append(structlog.testing.LogCapture())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        cache_logger_on_first_use=True,
        # F12: route NDJSON to stderr. STDOUT is reserved for the MCP
        # JSON-RPC frame stream when the overlay runs as an MCP stdio server;
        # logs on STDOUT corrupt the protocol channel for strict clients.
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    # Set the root logger level
    import logging
    logging.basicConfig(level=getattr(logging, log_level))


# Production default: configure on import so any module that does
# ``from structlog import get_logger`` immediately gets the redacting pipeline.
configure(testing=False)
