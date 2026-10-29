"""Reusable title-bar dragging and explicit docking for panel workspaces."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QDockWidget, QMainWindow, QStyle, QTabBar, QWidget

from blab.ui.dock_targets import (
    CompassPosition,
    Edge,
    EqualiseAxis,
    PanelDropTarget,
    Point,
    Rect,
    aligned_layout_members,
    compass_placement,
    compass_target_rects,
    edge_placement,
    edge_target_rects,
    panel_preview_rect,
    panel_under_cursor,
    preview_rect,
    resolve_drop_target,
    top_level_layout_members,
)


def _qrect(rect: Rect) -> QRect:
    return QRect(rect.x, rect.y, rect.width, rect.height)


def _orientation(axis: EqualiseAxis) -> Qt.Orientation:
    return Qt.Horizontal if axis == EqualiseAxis.HORIZONTAL else Qt.Vertical


class PanelDropOverlay(QWidget):
    """Workspace overlay that paints drop targets and owns an active drag."""

    def __init__(self, controller: PanelDockController, workspace: QMainWindow):
        super().__init__(workspace)
        self._controller = controller
        self._dragged_panel: QDockWidget | None = None
        self._hovered_target: PanelDropTarget | None = None
        self._compass_panel_id: str | None = None
        self._panel_rects: dict[str, Rect] = {}
        self.setObjectName("panelDropOverlay")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.hide()

    def begin(self, panel: QDockWidget, global_cursor: QPoint) -> None:
        self._dragged_panel = panel
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.MouseFocusReason)
        self.grabMouse()
        self.grabKeyboard()
        self._update_hover(global_cursor)

    def end(self) -> None:
        if self.mouseGrabber() is self:
            self.releaseMouse()
        if self.keyboardGrabber() is self:
            self.releaseKeyboard()
        self._dragged_panel = None
        self._hovered_target = None
        self._compass_panel_id = None
        self._panel_rects = {}
        self.hide()

    def _update_hover(self, global_cursor: QPoint) -> None:
        local = self.mapFromGlobal(global_cursor)
        workspace = Rect(0, 0, self.width(), self.height())
        cursor = Point(local.x(), local.y())
        self._panel_rects = self._controller.docked_panel_rects()
        excluded = self._controller.dragged_group_ids()
        self._compass_panel_id = panel_under_cursor(cursor, self._panel_rects, excluded)
        self._hovered_target = resolve_drop_target(cursor, workspace, self._panel_rects, excluded)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._update_hover(event.globalPosition().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.LeftButton or self._dragged_panel is None:
            event.ignore()
            return
        panel = self._dragged_panel
        cursor = event.globalPosition().toPoint()
        target = self._hovered_target
        self.end()
        self._controller.finish_drag(panel, cursor, target)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key_Escape and self._dragged_panel is not None:
            self.end()
            self._controller.cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        workspace = Rect(0, 0, self.width(), self.height())
        highlight = self.palette().color(self.palette().ColorRole.Highlight)
        target_fill = QColor(highlight)
        target_fill.setAlpha(90)
        preview_fill = QColor(highlight)
        preview_fill.setAlpha(55)

        painter = QPainter(self)
        painter.setPen(QPen(highlight, 2))
        if self._hovered_target is not None:
            excluded = self._controller.dragged_group_ids()
            preview_panel_rects = {
                panel_id: rect for panel_id, rect in self._panel_rects.items() if panel_id not in excluded
            }
            if self._hovered_target.edge is not None:
                placement = edge_placement(self._hovered_target.edge)
                member_count = len(top_level_layout_members(preview_panel_rects, placement.axis))
                hovered_preview = preview_rect(workspace, self._hovered_target.edge, member_count)
            else:
                panel_id = self._hovered_target.panel_id or ""
                position = self._hovered_target.position
                hovered_preview = (
                    panel_preview_rect(preview_panel_rects, panel_id, position)
                    if panel_id in preview_panel_rects and position is not None
                    else None
                )
            if hovered_preview is not None:
                painter.fillRect(_qrect(hovered_preview), preview_fill)
        for target in edge_target_rects(workspace).values():
            rect = _qrect(target).adjusted(5, 5, -5, -5)
            painter.fillRect(rect, target_fill)
            painter.drawRect(rect)
        compass_panel = self._panel_rects.get(self._compass_panel_id or "")
        if compass_panel is not None:
            for target in compass_target_rects(compass_panel).values():
                rect = _qrect(target).adjusted(3, 3, -3, -3)
                painter.fillRect(rect, target_fill)
                painter.drawRect(rect)


class PanelDockController:
    """Attach explicit panel dragging and placement to a native Qt workspace."""

    _DOCK_AREAS = {
        Edge.LEFT: Qt.LeftDockWidgetArea,
        Edge.RIGHT: Qt.RightDockWidgetArea,
        Edge.TOP: Qt.TopDockWidgetArea,
        Edge.BOTTOM: Qt.BottomDockWidgetArea,
    }
    _EDGE_CORNERS = {
        Edge.LEFT: (Qt.TopLeftCorner, Qt.BottomLeftCorner),
        Edge.RIGHT: (Qt.TopRightCorner, Qt.BottomRightCorner),
        Edge.TOP: (Qt.TopLeftCorner, Qt.TopRightCorner),
        Edge.BOTTOM: (Qt.BottomLeftCorner, Qt.BottomRightCorner),
    }

    def __init__(self, workspace: QMainWindow, panels: Iterable[QDockWidget] = ()):
        self.workspace = workspace
        self.overlay = PanelDropOverlay(self, workspace)
        self._dragged_panel: QDockWidget | None = None
        self._panels: list[QDockWidget] = []
        for panel in panels:
            self.register_panel(panel)

    def register_panel(self, panel: QDockWidget) -> None:
        """Enable custom dragging for one panel's title bar."""
        if panel not in self._panels:
            self._panels.append(panel)
        title_bar = panel.titleBarWidget()
        if title_bar is not None and hasattr(title_bar, "set_dock_controller"):
            title_bar.set_dock_controller(self)

    def start_drag(self, panel: QDockWidget, global_cursor: QPoint) -> None:
        self._dragged_panel = panel
        self.overlay.begin(panel, global_cursor)

    def cancel_drag(self) -> None:
        """Cancel without touching the native layout."""
        self._dragged_panel = None

    @staticmethod
    def _panel_id(panel: QDockWidget) -> str:
        return panel.objectName() or f"panel-{id(panel)}"

    def docked_panel_rects(self) -> dict[str, Rect]:
        """Return overlay-local geometry for eligible docked panels."""
        rects: dict[str, Rect] = {}
        for panel in self._panels:
            if panel.isFloating() or panel.isHidden():
                continue
            origin = panel.mapTo(self.workspace, QPoint(0, 0))
            rects[self._panel_id(panel)] = Rect(origin.x(), origin.y(), panel.width(), panel.height())
        return rects

    def _separator_extent(self) -> int:
        return self.workspace.style().pixelMetric(QStyle.PM_DockWidgetSeparatorExtent)

    def _panel_slot_rect(self, panel: QDockWidget, rect: Rect) -> Rect:
        """Include the native tab bar in a tab group's spatial slot."""
        if not self.workspace.tabifiedDockWidgets(panel):
            return rect
        for tab_bar in self.workspace.findChildren(QTabBar):
            if not tab_bar.isVisible():
                continue
            origin = tab_bar.mapTo(self.workspace, QPoint(0, 0))
            tab_rect = Rect(origin.x(), origin.y(), tab_bar.width(), tab_bar.height())
            touches_horizontally = (tab_rect.x, tab_rect.width) == (rect.x, rect.width) and (
                tab_rect.y == rect.bottom or tab_rect.bottom == rect.y
            )
            touches_vertically = (tab_rect.y, tab_rect.height) == (rect.y, rect.height) and (
                tab_rect.x == rect.right or tab_rect.right == rect.x
            )
            if touches_horizontally or touches_vertically:
                left = min(rect.x, tab_rect.x)
                top = min(rect.y, tab_rect.y)
                return Rect(
                    left,
                    top,
                    max(rect.right, tab_rect.right) - left,
                    max(rect.bottom, tab_rect.bottom) - top,
                )
        return rect

    def dragged_group_ids(self) -> set[str]:
        """Exclude the dragged panel and the tabs occupying its current position."""
        if self._dragged_panel is None or self._dragged_panel.isFloating():
            return set()
        group = [self._dragged_panel, *self.workspace.tabifiedDockWidgets(self._dragged_panel)]
        return {self._panel_id(panel) for panel in group}

    def finish_drag(
        self,
        panel: QDockWidget,
        global_cursor: QPoint,
        target: Edge | PanelDropTarget | None,
    ) -> None:
        self._dragged_panel = None
        if target is not None:
            self.drop_panel(panel, target)
            return
        panel_rect = QRect(panel.mapToGlobal(QPoint(0, 0)), panel.size())
        if not panel.isFloating() and panel_rect.contains(global_cursor):
            return
        departed_groups = self._departed_groups(panel)
        panel.setFloating(True)
        panel.show()
        panel.move(global_cursor - QPoint(panel.width() // 2, 12))
        self._equalise_departed_groups(departed_groups)

    def drop_panel(self, panel: QDockWidget, target: Edge | PanelDropTarget) -> None:
        """Place ``panel`` at a resolved target through the public seam."""
        if isinstance(target, Edge):
            target = PanelDropTarget.outer(target)
        if target.edge is not None:
            if self._edge_drop_is_unchanged(panel, target.edge):
                return
            departed_groups = self._departed_groups(panel)
            self._drop_at_edge(panel, target.edge, departed_groups)
            return
        target_panel = next(
            (candidate for candidate in self._panels if self._panel_id(candidate) == target.panel_id),
            None,
        )
        if target_panel is None or target_panel is panel or target_panel.isFloating():
            return
        position = target.position
        if position == CompassPosition.CENTER:
            departed_groups = self._departed_groups(panel)
            self.workspace.removeDockWidget(panel)
            self.workspace.addDockWidget(self.workspace.dockWidgetArea(target_panel), panel)
            self.workspace.tabifyDockWidget(target_panel, panel)
            panel.show()
            panel.raise_()
            self._equalise_departed_groups(departed_groups)
            return
        if position is None:
            return
        placement = compass_placement(position)
        if placement is None:
            return
        departed_groups = self._departed_groups(panel)
        axis = placement.axis
        orientation = _orientation(axis)
        panel_rects = self.docked_panel_rects()
        panel_rects.pop(self._panel_id(panel), None)
        target_panel_id = self._panel_id(target_panel)
        panel_rects[target_panel_id] = self._panel_slot_rect(
            target_panel,
            panel_rects[target_panel_id],
        )
        member_ids = aligned_layout_members(
            panel_rects,
            target_panel_id,
            axis,
            separator_extent=self._separator_extent(),
        )
        target_tabs = self.workspace.tabifiedDockWidgets(target_panel)
        for target_tab in target_tabs:
            self.workspace.removeDockWidget(target_tab)
        panel.setFloating(False)
        area = self.workspace.dockWidgetArea(target_panel)
        self.workspace.addDockWidget(area, panel, orientation)
        if placement.before:
            self.workspace.splitDockWidget(panel, target_panel, orientation)
        elif target_tabs:
            self.workspace.splitDockWidget(panel, target_panel, orientation)
            self.workspace.splitDockWidget(target_panel, panel, orientation)
        else:
            self.workspace.splitDockWidget(target_panel, panel, orientation)
        for target_tab in target_tabs:
            self.workspace.addDockWidget(area, target_tab, orientation)
            target_tab.show()
            self.workspace.tabifyDockWidget(target_panel, target_tab)
        panel.show()
        self._equalise_departed_groups(departed_groups)
        members = [
            candidate
            for panel_id in member_ids
            for candidate in self._panels
            if self._panel_id(candidate) == panel_id and candidate is not panel
        ]
        self.workspace.resizeDocks([*members, panel], [1] * (len(members) + 1), orientation)
        target_panel.raise_()

    def _edge_drop_is_unchanged(self, panel: QDockWidget, edge: Edge) -> bool:
        """Return whether ``panel`` already occupies the requested outer edge."""
        if panel.isFloating() or panel.isHidden():
            return False
        rects: dict[str, Rect] = {}
        for candidate in self.workspace.findChildren(QDockWidget):
            if candidate.isFloating() or candidate.isHidden():
                continue
            origin = candidate.mapTo(self.workspace, QPoint(0, 0))
            rects[self._panel_id(candidate)] = Rect(
                origin.x(),
                origin.y(),
                candidate.width(),
                candidate.height(),
            )
        panel_rect = rects.get(self._panel_id(panel))
        if panel_rect is None:
            origin = panel.mapTo(self.workspace, QPoint(0, 0))
            panel_rect = Rect(origin.x(), origin.y(), panel.width(), panel.height())
            rects[self._panel_id(panel)] = panel_rect
        left = min(rect.x for rect in rects.values())
        right = max(rect.right for rect in rects.values())
        top = min(rect.y for rect in rects.values())
        bottom = max(rect.bottom for rect in rects.values())
        placement = edge_placement(edge)
        if placement.axis == EqualiseAxis.HORIZONTAL:
            boundary_matches = panel_rect.x == left if placement.before else panel_rect.right == right
            return boundary_matches and (panel_rect.y, panel_rect.bottom) == (top, bottom)
        boundary_matches = panel_rect.y == top if placement.before else panel_rect.bottom == bottom
        return boundary_matches and (panel_rect.x, panel_rect.right) == (left, right)

    def _departed_groups(
        self,
        panel: QDockWidget,
    ) -> list[tuple[EqualiseAxis, list[QDockWidget]]]:
        if panel.isFloating() or panel.isHidden() or self.workspace.tabifiedDockWidgets(panel):
            return []
        panel_id = self._panel_id(panel)
        panel_rects = self.docked_panel_rects()
        groups: list[tuple[EqualiseAxis, list[QDockWidget]]] = []
        for axis in (EqualiseAxis.HORIZONTAL, EqualiseAxis.VERTICAL):
            member_ids = aligned_layout_members(
                panel_rects,
                panel_id,
                axis,
                separator_extent=self._separator_extent(),
            )
            if len(member_ids) <= 1:
                continue
            members: list[QDockWidget] = []
            seen_tab_groups: set[frozenset[int]] = set()
            for member_id in member_ids:
                candidate = next(
                    (item for item in self._panels if self._panel_id(item) == member_id),
                    None,
                )
                if candidate is None or candidate is panel:
                    continue
                tab_group = [candidate, *self.workspace.tabifiedDockWidgets(candidate)]
                tab_group_key = frozenset(id(item) for item in tab_group)
                if tab_group_key in seen_tab_groups:
                    continue
                seen_tab_groups.add(tab_group_key)
                representative = next((item for item in tab_group if item.isVisible()), candidate)
                members.append(representative)
            if len(members) > 1:
                groups.append((axis, members))
        return groups

    def _equalise_departed_groups(
        self,
        groups: list[tuple[EqualiseAxis, list[QDockWidget]]],
    ) -> None:
        self.workspace.layout().activate()
        for axis, members in groups:
            orientation = _orientation(axis)
            representatives: list[QDockWidget] = []
            for member in members:
                tab_group = [member, *self.workspace.tabifiedDockWidgets(member)]

                def visible_area(candidate: QDockWidget) -> int:
                    origin = candidate.mapTo(self.workspace, QPoint(0, 0))
                    candidate_rect = QRect(origin, candidate.size())
                    visible_rect = candidate_rect.intersected(self.workspace.rect())
                    return visible_rect.width() * visible_rect.height()

                representative = max(tab_group, key=visible_area)
                if representative not in representatives:
                    representatives.append(representative)
            self.workspace.resizeDocks(
                representatives,
                [1] * len(representatives),
                orientation,
            )

    def _drop_at_edge(
        self,
        panel: QDockWidget,
        edge: Edge,
        departed_groups: list[tuple[EqualiseAxis, list[QDockWidget]]],
    ) -> None:
        axis = edge_placement(edge).axis
        orientation = _orientation(axis)
        panel_rects = self.docked_panel_rects()
        panel_rects.pop(self._panel_id(panel), None)
        member_ids = top_level_layout_members(panel_rects, axis)
        area = self._DOCK_AREAS[edge]
        panel.setFloating(False)
        self.workspace.removeDockWidget(panel)
        for corner in self._EDGE_CORNERS[edge]:
            self.workspace.setCorner(corner, area)
        self.workspace.addDockWidget(area, panel, orientation)
        panel.show()
        self.workspace.layout().activate()
        self._equalise_departed_groups(departed_groups)
        members = [
            candidate
            for panel_id in member_ids
            for candidate in self._panels
            if self._panel_id(candidate) == panel_id and candidate is not panel
        ]
        size = (self.workspace.width() if orientation == Qt.Horizontal else self.workspace.height()) // (
            len(members) + 1
        )
        for member in [*members, panel]:
            self.workspace.resizeDocks([member], [size], orientation)


__all__ = ["PanelDockController", "PanelDropOverlay"]
