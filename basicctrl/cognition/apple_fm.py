"""Apple FM tier-0 binary classifier with hard enum validation (P6, P7 mitigation).

Per D-02 (04-CONTEXT.md): Apple FoundationModels 3B text-only classifier.
Output MUST be hard-validated against Literal enum BEFORE use.

P6 mitigation: Reject multi-field JSON responses; validate against allowed enum.
P7 mitigation: Type-system gate — input has no pixels field; visual context must be
OCR'd or uitag-described first (caller responsibility).

Apple FM constraints:
- Text-only API (no image input as of macOS 26.4)
- 4096 context token cap
- ~50% hallucination on complex schemas; only trust small-enum output
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

from cua_overlay.cognition.schemas import AppleFMOutput

_log = structlog.get_logger()

# Flag for test mocking — ImportError during tests is expected
HAS_APPLE_FM = True
try:
    import apple_fm_sdk  # type: ignore[import-not-found]
except ImportError:
    HAS_APPLE_FM = False


class AppleFMClassifier:
    """Apple FoundationModels tier-0 binary classifier.

    Per D-02, P6, P7:
    - Input: text state description only (no pixels)
    - Output: hard-validated Literal enum
    - Validation failure raises ValueError; caller falls through to next tier
    """

    async def classify(
        self,
        state_description: str,
        decision_context: str = "route_translator",
    ) -> Optional[AppleFMOutput]:
        """Classify a state description into a small enum.

        Args:
            state_description: Textual scene description (~500 tokens max per P6).
                For visual context, caller must OCR + uitag.describe() first.
            decision_context: Hint about what we're deciding
                (e.g., "route_translator", "binary_yes_no", "small_enum").

        Returns:
            AppleFMOutput with hard-validated enum, or None on validation failure.

        Raises:
            ValueError: if response contains JSON or invalid enum value (P6).
        """
        if not HAS_APPLE_FM:
            _log.warning(
                "apple_fm.sdk_unavailable",
                context=decision_context,
            )
            return None

        # Construct prompt for Apple FM — binary or small-enum only
        prompt = self._make_prompt(state_description, decision_context)

        try:
            # Apple FM SDK call (sync, wrapped in to_thread)
            response = await asyncio.to_thread(
                self._call_apple_fm,
                prompt,
            )
        except TimeoutError as exc:
            _log.warning(
                "apple_fm.timeout",
                context=decision_context,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "apple_fm.call_failed",
                error=str(exc),
                context=decision_context,
            )
            return None

        if not response:
            return None

        # P6 mitigation: reject JSON responses (hallucination marker)
        if "{" in response or '"' in response:
            _log.warning(
                "apple_fm.json_hallucination_detected",
                response=response[:100],  # log first 100 chars
                context=decision_context,
            )
            return None

        # Hard-validate output against Literal enum
        # Normalize response: uppercase T1-T5, lowercase retry/escalate/abort
        normalized = response.strip()
        if normalized.lower() in ["retry", "escalate", "abort"]:
            normalized = normalized.lower()
        else:
            normalized = normalized.upper()

        try:
            return AppleFMOutput(output=normalized)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "apple_fm.validation_failed",
                response=response,
                error=str(exc),
                context=decision_context,
            )
            return None

    def _make_prompt(self, state_description: str, context: str) -> str:
        """Construct a minimal prompt for Apple FM (P6 constraint: small-enum only).

        Per D-02: FM gets condensed (<500 token) text summary only.
        No full screenshots, no full DOM, no full state graph.
        """
        # Map context hints to enum suggestions
        context_hints = {
            "route_translator": (
                "Respond with exactly ONE of: T1, T2, T3, T4, T5, retry, escalate, abort"
            ),
            "binary_yes_no": (
                "Respond with exactly: yes or no"
            ),
            "small_enum": (
                "Respond with exactly ONE of the allowed values"
            ),
        }
        hint = context_hints.get(context, "Respond with a single word enum value")

        prompt = (
            f"Given the current UI state:\n{state_description}\n\n"
            f"Which translator should route this action? {hint}\n"
            f"Respond with ONE WORD ONLY."
        )
        return prompt

    def _call_apple_fm(self, prompt: str) -> str:
        """Sync wrapper around Apple FM SDK call.

        This runs in asyncio.to_thread, so blocking is OK.
        """
        if not HAS_APPLE_FM:
            return ""

        try:
            # apple-fm-sdk API: GenerateTextRequest + sync execute
            result = apple_fm_sdk.generate_text(
                prompt,
                parameters={
                    "temperature": 0.0,  # Deterministic (no hallucination variance)
                    "max_tokens": 10,  # Enum response fits in <10 tokens
                },
            )
            # apple-fm-sdk returns text directly or wrapped in a response object
            return str(result) if result else ""
        except Exception as exc:  # noqa: BLE001
            _log.error("apple_fm.sdk_call_error", error=str(exc))
            return ""
