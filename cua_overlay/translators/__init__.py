"""Phase 2 Translators package — T1-T5 protocol implementations.

Per CONTEXT.md D-01..D-08. Each translator resolves a target by spec
(via AX, CDP, AppleScript, Vision/uitag, or Pixel) and returns a
TranslatorTarget that a Channel fires on.

Default channel binding (D-14):
    T1 → C2 (kAXPress)        |  T2 → C5 (CDP Input.dispatch)
    T3 → C4 (AppleScript)     |  T4 → C1 (CGEvent public)
    T5 → C3 (CGEvent postToPid with cursor)
"""
from cua_overlay.translators.base import (
    TargetSpec,
    Translator,
    TranslatorTarget,
)
from cua_overlay.translators.registry import TranslatorRegistry

__all__ = [
    "TargetSpec",
    "Translator",
    "TranslatorTarget",
    "TranslatorRegistry",
]
