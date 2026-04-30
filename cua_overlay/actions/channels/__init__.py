"""Phase 2 Channels — C1..C5 action delivery primitives.

Per CONTEXT.md D-14 default mapping:
    C1 SLEventPostToPid (Phase 6 SkyLight; Phase 2 = public CGEvent)
    C2 AX kAXPress
    C3 CGEvent.postToPid (with cursor)
    C4 AppleScript
    C5 CDP Input.dispatchMouseEvent

Each channel implements the Channel Protocol (base.py) and reads the
shared IdempotencyTokenStore for D-17 atomic claim before fire.
"""
from cua_overlay.actions.channels.base import Channel, ChannelOutcome
from cua_overlay.actions.channels.c2_ax_press import C2AXPressChannel
from cua_overlay.actions.channels.c4_applescript import C4AppleScriptChannel
from cua_overlay.actions.channels.c5_cdp_input import C5CDPInputChannel

__all__ = [
    "Channel",
    "ChannelOutcome",
    "C2AXPressChannel",
    "C4AppleScriptChannel",
    "C5CDPInputChannel",
]
