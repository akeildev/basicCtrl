"""Cognition layer exception types.

`CognitionDisabledError` is raised at construction time when an LLM-backed
cognition module cannot start (typically a missing API key). Callers
(e.g. `basicctrl.mcp_server.main`) catch it and route to a stub/fallback
implementation so the overall system stays online without that module.

Distinct from `ValueError`: misconfiguration vs. legitimate "feature off"
signal. main.py only catches the latter.
"""
from __future__ import annotations


class CognitionDisabledError(RuntimeError):
    """Raised when a cognition module cannot be constructed.

    Usually missing API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`).
    Caller should catch and substitute a stub implementation.
    """

    def __init__(self, module: str, reason: str) -> None:
        super().__init__(f"{module} disabled: {reason}")
        self.module = module
        self.reason = reason
