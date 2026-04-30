"""Typed AX error hierarchy.

Maps native macOS AX error codes from ``<HIServices/AXError.h>`` to typed Python
exceptions so downstream try/except blocks read clearly and so we can raise
T-1-04 (TCC revocation) signal cleanly to the TCCMonitor in Plan 02.

Canonical codes (from /Library/Developer/CommandLineTools/SDKs/MacOSX26.4.sdk/
System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/
HIServices.framework/Versions/A/Headers/AXError.h on macOS 26.4 — read live at
scaffold time per Plan 01-03 Task 1 step 0):

    kAXErrorSuccess                              =      0
    kAXErrorFailure                              = -25200
    kAXErrorIllegalArgument                      = -25201
    kAXErrorInvalidUIElement                     = -25202
    kAXErrorInvalidUIElementObserver             = -25203
    kAXErrorCannotComplete                       = -25204
    kAXErrorAttributeUnsupported                 = -25205
    kAXErrorActionUnsupported                    = -25206
    kAXErrorNotificationUnsupported              = -25207
    kAXErrorNotImplemented                       = -25208
    kAXErrorNotificationAlreadyRegistered        = -25209
    kAXErrorNotificationNotRegistered            = -25210
    kAXErrorAPIDisabled                          = -25211
    kAXErrorNoValue                              = -25212
    kAXErrorParameterizedAttributeUnsupported    = -25213
    kAXErrorNotEnoughPrecision                   = -25214

PyObjC 12.1 exports these symbols from ``HIServices``; we import them directly
so the integer values come from the live framework, not a frozen literal table.
"""
from __future__ import annotations

# Import the canonical constants from PyObjC's HIServices binding so the values
# are sourced from the live AXError.h on the build machine, not duplicated as
# integer literals in our code. macOS-version drift is invisible to us — the
# constants stay aligned with whatever HIServices ships.
try:  # pragma: no cover — pyobjc 12.1 always provides these on macOS
    from HIServices import (  # type: ignore[import-not-found]
        kAXErrorActionUnsupported,
        kAXErrorAPIDisabled,
        kAXErrorAttributeUnsupported,
        kAXErrorCannotComplete,
        kAXErrorInvalidUIElement,
        kAXErrorNotificationUnsupported,
    )
except ImportError:  # pragma: no cover — non-macOS dev hosts only
    # Fallback to canonical values from AXError.h verified above. These match
    # macOS 14-26.4 inclusive; if Apple ever changes them we'll see test failures.
    kAXErrorInvalidUIElement = -25202
    kAXErrorCannotComplete = -25204
    kAXErrorAttributeUnsupported = -25205
    kAXErrorActionUnsupported = -25206
    kAXErrorNotificationUnsupported = -25207
    kAXErrorAPIDisabled = -25211


class AXError(Exception):
    """Base class for typed AX errors.

    The numeric ``code`` is preserved on the exception so downstream handlers
    can match on it without parsing the string form.
    """

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(f"{message} (code={code})")
        self.code = code


class AXAPIDisabledError(AXError):
    """``kAXErrorAPIDisabled`` (-25211) — TCC revoked or AX disabled.

    Plan 01-02's TCCMonitor catches this and emits a structured ``tcc_revoked``
    event so callers can pause work and prompt for re-grant (T-1-04 mitigation).
    """


class AXCannotCompleteError(AXError):
    """``kAXErrorCannotComplete`` (-25204) — main-thread saturation, app busy.

    Pitfall P2 / cmux #2985 surface signal: the TokenBucket is supposed to keep
    us BELOW the rate where this fires, but if it does, we got unlucky and the
    caller should fall back to cached state with reduced confidence.
    """


class AXNotificationUnsupportedError(AXError):
    """``kAXErrorNotificationUnsupported`` (-25207) — common on web/Electron content.

    Plan 02's classifier flips ``ax_observer_works=False`` when this fires.
    """


class AXInvalidUIElementError(AXError):
    """``kAXErrorInvalidUIElement`` (-25202) — stale ``AXUIElement`` reference.

    Element was destroyed or the window closed between observation and read.
    Caller should re-resolve via ``composite_key`` (Pitfall P14 mitigation).
    """


class AXAttributeUnsupportedError(AXError):
    """``kAXErrorAttributeUnsupported`` (-25205) — attribute not on this element."""


class AXActionUnsupportedError(AXError):
    """``kAXErrorActionUnsupported`` (-25206) — action not on this element."""


# Native code → exception class mapping. Keys are sourced from the live
# HIServices import above, so the integer values come from AXError.h on the
# build machine. Code that catches ``AXError`` will match every subclass.
_ERROR_CODE_MAP: dict[int, type[AXError]] = {
    int(kAXErrorInvalidUIElement): AXInvalidUIElementError,
    int(kAXErrorCannotComplete): AXCannotCompleteError,
    int(kAXErrorAttributeUnsupported): AXAttributeUnsupportedError,
    int(kAXErrorActionUnsupported): AXActionUnsupportedError,
    int(kAXErrorNotificationUnsupported): AXNotificationUnsupportedError,
    int(kAXErrorAPIDisabled): AXAPIDisabledError,
}


def axerror_from_code(code: int, message: str = "AX error") -> AXError:
    """Return an instance of the matching ``AXError`` subclass for ``code``.

    Falls back to plain ``AXError`` for codes outside the map so callers always
    get a typed exception. ``code`` is recorded on the returned exception.
    """
    cls = _ERROR_CODE_MAP.get(int(code), AXError)
    return cls(message, code=int(code))
