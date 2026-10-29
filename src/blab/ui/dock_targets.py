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
class Placement:
    """Axis and ordering shared by edge and compass placements."""

    axis: EqualiseAxis
    before: bool


_EDGE_PLACEMENTS = {
    Edge.LEFT: Placement(EqualiseAxis.HORIZONTAL, True),
    Edge.RIGHT: Placement(EqualiseAxis.HORIZONTAL, False),
    Edge.TOP: Placement(EqualiseAxis.VERTICAL, True),
    Edge.BOTTOM: Placement(EqualiseAxis.VERTICAL, False),
}
_COMPASS_PLACEMENTS = {
    CompassPosition.LEFT: Placement(EqualiseAxis.HORIZONTAL, True),
    CompassPosition.RIGHT: Placement(EqualiseAxis.HORIZONTAL, False),
    CompassPosition.TOP: Placement(EqualiseAxis.VERTICAL, True),
    CompassPosition.BOTTOM: Placement(EqualiseAxis.VERTICAL, False),
}


def edge_placement(edge: Edge) -> Placement:
    """Return the axis and ordering for an outer-edge drop."""
    return _EDGE_PLACEMENTS[edge]


def compass_placement(position: CompassPosition) -> Placement | None:
    """Return side-placement metadata, or ``None`` for the centre target."""
    return _COMPASS_PLACEMENTS.get(position)


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
) -> Edge | None:
    """Resolve a cursor to an outer edge."""
    if not workspace.contains(cursor):
        return None
    for edge, target in edge_target_rects(workspace).items():
        if target.contains(cursor):
            return edge
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
    *,
    separator_extent: int = 0,
) -> tuple[str, ...]:
    """Return the contiguous logical run containing ``anchor``.

    Native dock layouts may round sibling geometry by one pixel and place a
    style-defined separator between adjacent slots. Coincidentally aligned
    slots beyond that separator do not belong to the affected run.
    """
    anchor = panel_rects.get(anchor_panel_id)
    if anchor is None:
        return ()

    def is_aligned(rect: Rect) -> bool:
        if axis == EqualiseAxis.HORIZONTAL:
            return abs(rect.y - anchor.y) <= 1 and abs(rect.bottom - anchor.bottom) <= 1
        return abs(rect.x - anchor.x) <= 1 and abs(rect.right - anchor.right) <= 1

    representatives: dict[Rect, str] = {anchor: anchor_panel_id}
    for panel_id, rect in panel_rects.items():
        if is_aligned(rect) and rect not in representatives:
            representatives[rect] = panel_id
    coordinate = (lambda item: item[0].x) if axis == EqualiseAxis.HORIZONTAL else (lambda item: item[0].y)
    ordered = sorted(representatives.items(), key=coordinate)
    anchor_index = next(index for index, (rect, _) in enumerate(ordered) if rect == anchor)

    def gap(left: Rect, right: Rect) -> int:
        if axis == EqualiseAxis.HORIZONTAL:
            return right.x - left.right
        return right.y - left.bottom

    maximum_gap = max(0, separator_extent) + 1
    start = anchor_index
    while start > 0 and -1 <= gap(ordered[start - 1][0], ordered[start][0]) <= maximum_gap:
        start -= 1
    end = anchor_index + 1
    while end < len(ordered) and -1 <= gap(ordered[end - 1][0], ordered[end][0]) <= maximum_gap:
        end += 1
    return tuple(panel_id for _, panel_id in ordered[start:end])


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


def preview_rect(workspace: Rect, edge: Edge, existing_members: int = 1) -> Rect:
    """Return the final equal-share area for an outer-edge drop."""
    placement = edge_placement(edge)
    divisor = existing_members + 1
    if placement.axis == EqualiseAxis.HORIZONTAL:
        width = workspace.width // divisor
        left = workspace.x if placement.before else workspace.right - width
        return Rect(left, workspace.y, width, workspace.height)
    height = workspace.height // divisor
    top = workspace.y if placement.before else workspace.bottom - height
    return Rect(workspace.x, top, workspace.width, height)


def panel_preview_rect(
    panel_rects: Mapping[str, Rect],
    panel_id: str,
    position: CompassPosition,
) -> Rect | None:
    """Return the dropped panel's final equal-share area beside ``panel_id``."""
    panel = panel_rects.get(panel_id)
    if panel is None:
        return None
    placement = compass_placement(position)
    if placement is None:
        return panel
    member_ids = aligned_layout_members(panel_rects, panel_id, placement.axis)
    members = [panel_rects[member_id] for member_id in member_ids]
    target_index = member_ids.index(panel_id)
    insertion_index = target_index if placement.before else target_index + 1
    if placement.axis == EqualiseAxis.HORIZONTAL:
        left = min(rect.x for rect in members)
        right = max(rect.right for rect in members)
        width = (right - left) // (len(members) + 1)
        return Rect(left + insertion_index * width, panel.y, width, panel.height)
    top = min(rect.y for rect in members)
    bottom = max(rect.bottom for rect in members)
    height = (bottom - top) // (len(members) + 1)
    return Rect(panel.x, top + insertion_index * height, panel.width, height)


__all__ = [
    "CompassPosition",
    "Edge",
    "EqualiseAxis",
    "PanelDropTarget",
    "Point",
    "Rect",
    "compass_target_rects",
    "aligned_layout_members",
    "compass_placement",
    "edge_target_rects",
    "edge_placement",
    "panel_preview_rect",
    "panel_under_cursor",
    "preview_rect",
    "resolve_drop_target",
    "resolve_outer_edge_target",
    "top_level_layout_members",
]
