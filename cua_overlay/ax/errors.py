# STUB: replaced by Plan 01-03 on merge
"""Typed AX error hierarchy.

This is a Wave-2 import-compatibility stub. Plan 01-03 owns the real
implementation (see plan 01-03 Task 1). The orchestrator will overwrite this
file with Plan 01-03's full implementation via ``-X theirs`` strategy on merge.

Only the symbols Plan 01-04 imports are stubbed here:
- ``AXError`` (base class)
- ``AXAPIDisabledError``
- ``AXCannotCompleteError``
- ``AXNotificationUnsupportedError``
- ``AXInvalidUIElementError``
- ``axerror_from_code`` (factory)
"""
from __future__ import annotations


class AXError(Exception):
    """Base AX error. Real implementation in Plan 01-03."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(f"{message} (code={code})")
        self.code = code


class AXAPIDisabledError(AXError):
    """kAXErrorAPIDisabled — TCC revoked. Real impl in Plan 01-03."""


class AXCannotCompleteError(AXError):
    """kAXErrorCannotComplete — main-thread saturation. Real impl in Plan 01-03."""


class AXNotificationUnsupportedError(AXError):
    """kAXErrorNotificationUnsupported. Real impl in Plan 01-03."""


class AXInvalidUIElementError(AXError):
    """kAXErrorInvalidUIElement — stale ref. Real impl in Plan 01-03."""


def axerror_from_code(code: int, message: str = "AX error") -> AXError:
    """Factory mapping native AX codes to typed exceptions. Real impl in Plan 01-03."""
    # Minimal stub mapping; Plan 01-03 ships the canonical AXError.h table.
    mapping: dict[int, type[AXError]] = {
        -25202: AXInvalidUIElementError,
        -25204: AXCannotCompleteError,
        -25207: AXNotificationUnsupportedError,
        -25211: AXAPIDisabledError,
    }
    cls = mapping.get(code, AXError)
    return cls(message, code=code)
