"""Qt-free geometry for panel docking drop targets."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import Enum


class Edge(Enum):
    """An outer edge of a workspace."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class CompassPosition(Enum):
    """A placement relative to one docked panel."""

    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    CENTER = "center"


class EqualiseAxis(Enum):
    """The dimension shared equally by one logical dock row or column."""

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


@dataclass(frozen=True)
class PanelDropTarget:
    """One resolved outer-edge or panel-relative drop target."""

    edge: Edge | None = None
    panel_id: str | None = None
    position: CompassPosition | None = None

    @classmethod
    def outer(cls, edge: Edge) -> PanelDropTarget:
        return cls(edge=edge)

    @classmethod
    def panel(cls, panel_id: str, position: CompassPosition) -> PanelDropTarget:
        return cls(panel_id=panel_id, position=position)


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


def compass_target_rects(panel: Rect) -> dict[CompassPosition, Rect]:
    """Return the five large targets centred over a panel."""
    size = max(24, min(64, panel.width // 4, panel.height // 4))
    centre_x = panel.x + panel.width // 2
    centre_y = panel.y + panel.height // 2

    def target(offset_x: int, offset_y: int) -> Rect:
        return Rect(centre_x - size // 2 + offset_x, centre_y - size // 2 + offset_y, size, size)

    return {
        CompassPosition.LEFT: target(-size, 0),
        CompassPosition.RIGHT: target(size, 0),
        CompassPosition.TOP: target(0, -size),
        CompassPosition.BOTTOM: target(0, size),
        CompassPosition.CENTER: target(0, 0),
    }


def panel_under_cursor(
    cursor: Point,
    panel_rects: Mapping[str, Rect],
    excluded_panel_ids: Collection[str] = (),
) -> str | None:
    """Return the eligible docked panel under ``cursor``."""
    excluded = set(excluded_panel_ids)
    for panel_id, panel_rect in panel_rects.items():
        if panel_id not in excluded and panel_rect.contains(cursor):
            return panel_id
    return None


def resolve_drop_target(
    cursor: Point,
    workspace: Rect,
    panel_rects: Mapping[str, Rect],
    excluded_panel_ids: Collection[str] = (),
) -> PanelDropTarget | None:
    """Resolve one target, giving workspace edges precedence over a compass."""
    edge = resolve_outer_edge_target(cursor, workspace)
    if edge is not None:
        return PanelDropTarget.outer(edge)
    panel_id = panel_under_cursor(cursor, panel_rects, excluded_panel_ids)
    if panel_id is None:
        return None
    for position, target_rect in compass_target_rects(panel_rects[panel_id]).items():
        if target_rect.contains(cursor):
            return PanelDropTarget.panel(panel_id, position)
    return None


def aligned_layout_members(
    panel_rects: Mapping[str, Rect],
    anchor_panel_id: str,
    axis: EqualiseAxis,
) -> tuple[str, ...]:
    """Return one representative per logical group aligned with ``anchor``."""
    anchor = panel_rects.get(anchor_panel_id)
    if anchor is None:
        return ()

    def is_aligned(rect: Rect) -> bool:
        if axis == EqualiseAxis.HORIZONTAL:
            return (rect.y, rect.height) == (anchor.y, anchor.height)
        return (rect.x, rect.width) == (anchor.x, anchor.width)

    representatives: dict[Rect, str] = {anchor: anchor_panel_id}
    for panel_id, rect in panel_rects.items():
        if is_aligned(rect) and rect not in representatives:
            representatives[rect] = panel_id
    coordinate = (lambda item: item[0].x) if axis == EqualiseAxis.HORIZONTAL else (lambda item: item[0].y)
    return tuple(panel_id for _, panel_id in sorted(representatives.items(), key=coordinate))


def top_level_layout_members(
    panel_rects: Mapping[str, Rect],
    axis: EqualiseAxis,
) -> tuple[str, ...]:
    """Return one representative for each distinct top-level row or column."""
    representatives: dict[tuple[int, int], str] = {}
    for panel_id, rect in panel_rects.items():
        span = (rect.x, rect.width) if axis == EqualiseAxis.HORIZONTAL else (rect.y, rect.height)
        representatives.setdefault(span, panel_id)
    return tuple(representatives[span] for span in sorted(representatives))


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


def panel_preview_rect(panel: Rect, position: CompassPosition) -> Rect:
    """Return the area a panel-relative drop will occupy."""
    if position == CompassPosition.LEFT:
        return Rect(panel.x, panel.y, panel.width // 2, panel.height)
    if position == CompassPosition.RIGHT:
        left = panel.x + panel.width // 2
        return Rect(left, panel.y, panel.right - left, panel.height)
    if position == CompassPosition.TOP:
        return Rect(panel.x, panel.y, panel.width, panel.height // 2)
    if position == CompassPosition.BOTTOM:
        top = panel.y + panel.height // 2
        return Rect(panel.x, top, panel.width, panel.bottom - top)
    return panel


__all__ = [
    "CompassPosition",
    "Edge",
    "EqualiseAxis",
    "PanelDropTarget",
    "Point",
    "Rect",
    "compass_target_rects",
    "aligned_layout_members",
    "edge_target_rects",
    "panel_preview_rect",
    "panel_under_cursor",
    "preview_rect",
    "resolve_drop_target",
    "resolve_outer_edge_target",
    "top_level_layout_members",
]
