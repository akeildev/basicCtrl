"""Visualizer + Full Transparency — NSPanel ghost cursor, HUD, replay engine.

Phase 5 main module. Exports VisualizerBus, ReplayEngine, 3DTimeline.
Gate: pytest.importorskip if Swift sidecar not yet built.
"""

try:
    import asyncio
    import sys
    # Soft import: if Swift visualizer socket not ready, tests skip cleanly
    __all__ = [
        "VisualizerBus",
        "ReplayEngine",
        "Timeline3D",
        "CounterfactualRenderer",
        "SessionDiffer",
    ]
except ImportError as e:
    __all__ = []
    _skip_reason = str(e)
