"""Unit tests for basicctrl.ax.errors typed exception hierarchy.

Verifies that ``axerror_from_code(code)`` returns the right typed subclass for
each native AX error code, sourced from PyObjC HIServices's live exports of
``<HIServices/AXError.h>``.
"""
from __future__ import annotations

import pytest

from basicctrl.ax.errors import (
    AXActionUnsupportedError,
    AXAPIDisabledError,
    AXAttributeUnsupportedError,
    AXCannotCompleteError,
    AXError,
    AXInvalidUIElementError,
    AXNotificationUnsupportedError,
    axerror_from_code,
    kAXErrorActionUnsupported,
    kAXErrorAPIDisabled,
    kAXErrorAttributeUnsupported,
    kAXErrorCannotComplete,
    kAXErrorInvalidUIElement,
    kAXErrorNotificationUnsupported,
)


def test_canonical_axerror_h_values() -> None:
    """The constants imported from HIServices match the canonical AXError.h values.

    This is a tripwire: if Apple changes the integer values in macOS 27+, this
    test fails immediately and we know to re-run the AXError.h read.
    """
    assert int(kAXErrorInvalidUIElement) == -25202
    assert int(kAXErrorCannotComplete) == -25204
    assert int(kAXErrorAttributeUnsupported) == -25205
    assert int(kAXErrorActionUnsupported) == -25206
    assert int(kAXErrorNotificationUnsupported) == -25207
    assert int(kAXErrorAPIDisabled) == -25211


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (int(kAXErrorAPIDisabled), AXAPIDisabledError),
        (int(kAXErrorInvalidUIElement), AXInvalidUIElementError),
        (int(kAXErrorNotificationUnsupported), AXNotificationUnsupportedError),
        (int(kAXErrorCannotComplete), AXCannotCompleteError),
        (int(kAXErrorAttributeUnsupported), AXAttributeUnsupportedError),
        (int(kAXErrorActionUnsupported), AXActionUnsupportedError),
    ],
)
def test_error_class_mapping(code: int, expected: type[AXError]) -> None:
    """``axerror_from_code`` returns the right typed subclass for each code."""
    err = axerror_from_code(code)
    assert isinstance(err, expected)
    # Every typed subclass also IS an AXError.
    assert isinstance(err, AXError)
    # Code is preserved on the instance.
    assert err.code == code


def test_unknown_code_falls_back_to_axerror() -> None:
    """A code not in the map returns a plain ``AXError`` (not a KeyError)."""
    err = axerror_from_code(-99999)
    assert type(err) is AXError
    assert err.code == -99999


def test_error_message_includes_code() -> None:
    """``str(err)`` contains the numeric code so logs show what failed."""
    err = axerror_from_code(int(kAXErrorAPIDisabled), message="AX read failed")
    s = str(err)
    assert "-25211" in s
    assert "AX read failed" in s
