"""Pydantic v2 models for VisualizerBus IPC over unix socket.

Swift sidecar receives these as NDJSON; responses sent back same format.
Every field matches UI-SPEC.md dimensions and timing constraints.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ActionTier(str, Enum):
    """Translator tier classification."""

    T1 = "T1"  # AX
    T2 = "T2"  # CDP
    T3 = "T3"  # AppleScript
    T4 = "T4"  # Vision
    T5 = "T5"  # Pixel


class ActionChannel(str, Enum):
    """Execution channel classification."""

    C1 = "C1"  # SLEventPostToPid
    C2 = "C2"  # AX kAXPress
    C3 = "C3"  # CGEvent.postToPid
    C4 = "C4"  # AppleScript
    C5 = "C5"  # CDP Input.dispatch


class VerificationStatus(str, Enum):
    """Action verification outcome."""

    VERIFIED = "verified"
    HEALING = "healing"
    FAILED = "failed"


# Ghost Cursor IPC (UI-SPEC L59-73)
class GhostCursorCommand(BaseModel, frozen=True):
    """Send to Swift visualizer to animate ghost cursor lerp."""

    cmd: Literal["ghost_cursor"] = "ghost_cursor"
    x: float  # Target center X (from action_canonical.target_bbox.centerX)
    y: float  # Target center Y
    duration_ms: int = Field(ge=150, le=350)  # Ease-in-out lerp duration
    timestamp_ns: int  # Session-relative nanoseconds


# Element Highlight Box IPC (UI-SPEC L85-95)
class HighlightBoxCommand(BaseModel, frozen=True):
    """Send to Swift visualizer to draw element highlight."""

    cmd: Literal["highlight"] = "highlight"
    bbox_x: float
    bbox_y: float
    bbox_width: float
    bbox_height: float
    label: str = Field(max_length=40)  # Truncate to 40 chars per UI-SPEC
    tier: ActionTier
    channel: ActionChannel
    timestamp_ns: int


# HUD Action Entry IPC (UI-SPEC L141-150)
class HUDActionEntry(BaseModel, frozen=True):
    """One action in the HUD history."""

    action_type: str  # e.g., "click", "type", "scroll"
    target_label: str = Field(max_length=40)
    tier: ActionTier
    channel: ActionChannel
    status: VerificationStatus
    status_detail: Optional[str] = None  # e.g., "B2 regrounding" for HEALING


class HUDCommand(BaseModel, frozen=True):
    """Send HUD update to Swift visualizer."""

    cmd: Literal["hud_action"] = "hud_action"
    entries: list[HUDActionEntry]  # Last 8 actions (per UI-SPEC L150)
    session_start_iso: str  # ISO 8601 timestamp for "Session: ..." header
    goal: str = Field(max_length=40)  # Current task name, truncate
    timestamp_ns: int


# Config/Hotkey Command
class HotKeyCommand(BaseModel, frozen=True):
    """Hotkey event received from Swift (Cmd+Shift+V, etc.)"""

    cmd: Literal["hotkey"] = "hotkey"
    binding: str  # e.g., "cmd+shift+v" for toggle HUD
    action: str  # e.g., "toggle_hud", "open_timeline", "replay"
    timestamp_ns: int


# Replay metadata (OBS-01..04)
class ReplayFrameMetadata(BaseModel, frozen=True):
    """One frame in recording_metadata.ndjson."""

    frame_idx: int
    step_idx: Optional[int] = None  # null between steps
    timestamp_ms: int  # Session-relative milliseconds
    capture_error: Optional[str] = None  # null if no error


# Counterfactual state (OBS-05)
class CounterfactualState(BaseModel, frozen=True):
    """Reconstructed StateNode for an alternate recovery branch."""

    step_idx: int
    branch_name: str  # "B1", "B2", etc.
    was_winner: bool
    elements: list[dict]  # Simplified UIElement list from action_log
    timestamp_ns: int


# Session diff (OBS-06)
class DiffMarker(str, Enum):
    """Diff alignment markers."""

    SAME = "same"
    ADDED = "added"
    REMOVED = "removed"
    HEALED = "healed"  # Translator swap or selector change


class DiffLine(BaseModel, frozen=True):
    """One aligned step in session diff output."""

    marker: DiffMarker
    session_a_action: Optional[dict] = None  # From session A action_log
    session_b_action: Optional[dict] = None  # From session B action_log
    heal_reason: Optional[str] = None  # e.g., "T3 timeout"
