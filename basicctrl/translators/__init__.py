"""Phase 2 Translators package — T1-T5 protocol implementations.

Per CONTEXT.md D-01..D-08. Each translator resolves a target by spec
(via AX, CDP, AppleScript, Vision/uitag, or Pixel) and returns a
TranslatorTarget that a Channel fires on.

Default channel binding (D-14):
    T1 → C2 (kAXPress)        |  T2 → C5 (CDP Input.dispatch)
    T3 → C4 (AppleScript)     |  T4 → C1 (CGEvent public)
    T5 → C3 (CGEvent postToPid with cursor)
"""
from basicctrl.translators.base import (
    TargetSpec,
    Translator,
    TranslatorTarget,
)
from basicctrl.translators.registry import TranslatorRegistry
from basicctrl.translators.t1_ax import T1AXTranslator
from basicctrl.translators.t2_cdp import T2CDPTranslator
from basicctrl.translators.t3_applescript import T3AppleScriptTranslator
from basicctrl.translators.t4_vision import T4VisionTranslator
from basicctrl.translators.t5_pixel import T5PixelTranslator

__all__ = [
    "TargetSpec",
    "Translator",
    "TranslatorTarget",
    "TranslatorRegistry",
    "T1AXTranslator",
    "T2CDPTranslator",
    "T3AppleScriptTranslator",
    "T4VisionTranslator",
    "T5PixelTranslator",
]
