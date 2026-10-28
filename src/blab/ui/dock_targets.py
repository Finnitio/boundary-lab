"""Qt-free geometry for panel docking drop targets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Edge(Enum):
    """An outer edge of a workspace."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, point: Point) -> bool:
        return self.x <= point.x < self.right and self.y <= point.y < self.bottom


def edge_target_rects(workspace: Rect) -> dict[Edge, Rect]:
    """Return large, predictable hit areas along all workspace edges."""
    thickness = max(24, min(80, workspace.width // 5, workspace.height // 5))
    return {
        Edge.LEFT: Rect(workspace.x, workspace.y, thickness, workspace.height),
        Edge.RIGHT: Rect(workspace.right - thickness, workspace.y, thickness, workspace.height),
        Edge.TOP: Rect(workspace.x + thickness, workspace.y, workspace.width - 2 * thickness, thickness),
        Edge.BOTTOM: Rect(
            workspace.x + thickness,
            workspace.bottom - thickness,
            workspace.width - 2 * thickness,
            thickness,
        ),
    }


def resolve_outer_edge_target(
    cursor: Point,
    workspace: Rect,
    dragged_panel: Rect | None = None,
) -> Edge | None:
    """Resolve a cursor to an outer edge, or ``None`` for an unchanged drop."""
    if not workspace.contains(cursor):
        return None
    for edge, target in edge_target_rects(workspace).items():
        if target.contains(cursor):
            return edge
    if dragged_panel is not None and dragged_panel.contains(cursor):
        return None
    return None


def preview_rect(workspace: Rect, edge: Edge) -> Rect:
    """Return the half-workspace preview for an edge drop."""
    if edge == Edge.LEFT:
        return Rect(workspace.x, workspace.y, workspace.width // 2, workspace.height)
    if edge == Edge.RIGHT:
        left = workspace.x + workspace.width // 2
        return Rect(left, workspace.y, workspace.right - left, workspace.height)
    if edge == Edge.TOP:
        return Rect(workspace.x, workspace.y, workspace.width, workspace.height // 2)
    top = workspace.y + workspace.height // 2
    return Rect(workspace.x, top, workspace.width, workspace.bottom - top)


__all__ = ["Edge", "Point", "Rect", "edge_target_rects", "preview_rect", "resolve_outer_edge_target"]
