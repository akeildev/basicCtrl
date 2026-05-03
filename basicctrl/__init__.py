"""basicCtrl Python overlay package.

Sits above the vendored trycua/cua Swift driver at ``libs/cua-driver/`` and
owns the Pydantic state-graph contracts that every downstream phase imports.

The state subsystem (UIElement, Bbox, Edge, EdgeKind, Capability, Source,
ActionCanonical, HoarePre, HoarePost, StateGraph, CausalDAG, TemporalRingBuffer)
is the system-wide IPC contract. Do not redefine these types in downstream
modules — import them from ``basicctrl.state``.
"""
from __future__ import annotations

__version__ = "0.1.0"
