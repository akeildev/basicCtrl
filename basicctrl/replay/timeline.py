"""3D timeline — isometric projection of (time, app, depth) to 2D screen coords."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class TimelineNode:
    """Action node in 3D timeline."""
    step_idx: int
    timestamp_ms: int
    app_bundle: str
    tier: str  # T1-T5
    is_branch: bool = False
    branch_name: Optional[str] = None

    @property
    def x(self) -> float:
        """Time axis (milliseconds)."""
        return float(self.timestamp_ms)

    @property
    def y(self) -> str:
        """App/window axis (categorical)."""
        return self.app_bundle

    @property
    def z(self) -> int:
        """Depth axis (recovery branch level)."""
        return 1 if self.is_branch else 0


class Timeline3D:
    """Isometric 3D scatter plot data model."""

    def __init__(self, nodes: list[TimelineNode]):
        self.nodes = nodes
        self.apps = sorted(set(n.y for n in nodes))  # Unique apps for Y axis

    def project_to_2d(self, rotation_x: float = 0.3, rotation_z: float = 0.3) -> list[tuple[float, float]]:
        """Isometric projection: (time, app_idx, depth) -> (screen_x, screen_y).

        Simple orthographic projection:
        screen_x = x * cos(30°) - z * cos(30°)
        screen_y = y * spacing - (x + z) * sin(30°)
        """
        coords_2d = []

        for node in self.nodes:
            x = node.x
            y_idx = self.apps.index(node.y) if node.y in self.apps else 0
            z = float(node.z)

            # Isometric projection (standard 30° angles)
            cos_30 = math.cos(math.radians(30))
            sin_30 = math.sin(math.radians(30))

            screen_x = (x * cos_30) - (z * cos_30)
            screen_y = (y_idx * 50) - ((x + z) * sin_30)  # 50px per app row

            coords_2d.append((screen_x, screen_y))

        return coords_2d

    def get_node_color(self, node: TimelineNode) -> str:
        """Tier -> color mapping for Canvas rendering."""
        tier_colors = {
            "T1": "#007AFF",  # Blue
            "T2": "#32B4F9",  # Cyan
            "T3": "#FF9500",  # Orange
            "T4": "#34C759",  # Green
            "T5": "#FF3B30",  # Red
        }
        return tier_colors.get(node.tier, "#666666")
