"""ACT-04 — RacePolicy enum + dispatch table per D-09..D-12, D-30.

D-09: Race policy is per-action-class.
D-10: RACE allowlist — click_button, click, focus, scroll_to_position (absolute), hover.
D-11: SINGLE-CHANNEL allowlist — submit, send, delete, confirm, type_into_focused,
    set_value, drag_and_drop, scroll_by_delta, key_combo_destructive (cmd+s, cmd+enter,
    cmd+w, cmd+z).
D-12: SAFE-RACE key combos — cmd+c, cmd+v.
D-30: RacePolicy values — AUTO (server picks), RACE (force; caller-acknowledged risk),
    SINGLE_CHANNEL (force; safe override).

Server-side safety: T-2-09 mitigation — even when caller passes RACE, destructive
verbs are forced to SINGLE_CHANNEL with a structlog warning. The orchestrator
emits "race_policy.destructive_override_blocked" so the caller learns their
ack was rejected.

Action_type taxonomy verified against trycua/cua libs/cua-driver/Sources/CuaDriverServer/
ToolRegistry.swift:34-45 and Skyvern action_types.py:4-31.
"""
from __future__ import annotations

from enum import Enum

import structlog


class RacePolicy(str, Enum):
    """Per D-30."""

    AUTO = "auto"  # server picks via classifier — DEFAULT
    RACE = "race"  # force race; overrides denylist with caller-acknowledged risk
    SINGLE_CHANNEL = "single_channel"  # force single; safe override


# D-10: action_types where racing multiple channels is safe.
RACE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "click",
        "click_button",
        "right_click",
        "focus",
        "scroll_to_position",  # absolute coords — idempotent
        "hover",
    }
)

# D-11: action_types where multi-channel delivery would corrupt state.
SINGLE_CHANNEL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "submit",
        "send",
        "delete",
        "confirm",
        "type_into_focused",
        "type",
        "type_text",
        "type_text_chars",
        "set_value",
        "drag_and_drop",
        "drag",
        "scroll_by_delta",
    }
)

# D-11: destructive key combos. Each must be SINGLE_CHANNEL.
DESTRUCTIVE_COMBOS: frozenset[str] = frozenset(
    {
        "cmd+s",
        "cmd+enter",
        "cmd+return",
        "cmd+w",
        "cmd+z",
    }
)

# D-12: safe-race key combos.
SAFE_RACE_COMBOS: frozenset[str] = frozenset({"cmd+c", "cmd+v"})


_log = structlog.get_logger()


def resolve_race_policy(policy: RacePolicy, action_type: str) -> RacePolicy:
    """Resolve effective race policy for an action.

    AUTO consults D-10/D-11/D-12 dispatch tables.
    SINGLE_CHANNEL is always honored (safe direction).
    RACE is downgraded to SINGLE_CHANNEL for D-11 destructive verbs (T-2-09
    safety override) with a structured warning event.

    For key combos the action_type is expected to be of form "key_combo:cmd+s".
    """
    # SINGLE_CHANNEL is always safe to honor.
    if policy == RacePolicy.SINGLE_CHANNEL:
        return RacePolicy.SINGLE_CHANNEL

    # Determine intrinsic policy by action_type lookup.
    intrinsic = _classify_intrinsic(action_type)

    # AUTO uses the intrinsic.
    if policy == RacePolicy.AUTO:
        return intrinsic

    # RACE is requested. Honor only if intrinsic permits; otherwise force
    # SINGLE_CHANNEL with a warning (T-2-09).
    if policy == RacePolicy.RACE:
        if intrinsic == RacePolicy.SINGLE_CHANNEL:
            _log.warning(
                "race_policy.destructive_override_blocked",
                action_type=action_type,
                requested=policy.value,
                effective=RacePolicy.SINGLE_CHANNEL.value,
                reason=(
                    "action_type is on the D-11 destructive allowlist; "
                    "server forces SINGLE_CHANNEL even when caller requests RACE"
                ),
            )
            return RacePolicy.SINGLE_CHANNEL
        return RacePolicy.RACE

    # Defensive: unknown enum value.
    _log.warning("race_policy.unknown_policy", policy=str(policy))
    return RacePolicy.SINGLE_CHANNEL


def _classify_intrinsic(action_type: str) -> RacePolicy:
    """Lookup action_type in D-10/D-11/D-12 tables. Default = SINGLE_CHANNEL
    (conservative: unknown action_types do NOT race)."""
    # Key combo special case: action_type may be "key_combo:cmd+s".
    if action_type.startswith("key_combo:"):
        combo = action_type.split(":", 1)[1].lower()
        if combo in SAFE_RACE_COMBOS:
            return RacePolicy.RACE
        if combo in DESTRUCTIVE_COMBOS:
            return RacePolicy.SINGLE_CHANNEL
        # Unknown combo: conservative.
        return RacePolicy.SINGLE_CHANNEL

    if action_type in RACE_ALLOWLIST:
        return RacePolicy.RACE
    if action_type in SINGLE_CHANNEL_ALLOWLIST:
        return RacePolicy.SINGLE_CHANNEL
    # Default: unknown action_type → conservative single-channel.
    return RacePolicy.SINGLE_CHANNEL
