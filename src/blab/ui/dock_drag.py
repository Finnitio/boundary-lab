"""Reusable title-bar dragging and explicit docking for panel workspaces."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

from blab.ui.dock_targets import (
    CompassPosition,
    Edge,
    PanelDropTarget,
    Point,
    Rect,
    compass_target_rects,
    edge_target_rects,
    panel_preview_rect,
    panel_under_cursor,
    preview_rect,
    resolve_drop_target,
)


def _qrect(rect: Rect) -> QRect:
    return QRect(rect.x, rect.y, rect.width, rect.height)


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
            if self._hovered_target.edge is not None:
                hovered_preview = preview_rect(workspace, self._hovered_target.edge)
            else:
                panel_rect = self._panel_rects.get(self._hovered_target.panel_id or "")
                position = self._hovered_target.position
                hovered_preview = (
                    panel_preview_rect(panel_rect, position)
                    if panel_rect is not None and position is not None
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

    def __init__(self, workspace: QMainWindow):
        self.workspace = workspace
        self.overlay = PanelDropOverlay(self, workspace)
        self._dragged_panel: QDockWidget | None = None
        self._panels: list[QDockWidget] = []

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
        panel_rect = QRect(panel.mapToGlobal(QPoint(0, 0)), panel.size())
        if not panel.isFloating() and panel_rect.contains(global_cursor):
            return
        if target is not None:
            self.drop_panel(panel, target)
            return
        panel.setFloating(True)
        panel.show()
        panel.move(global_cursor - QPoint(panel.width() // 2, 12))

    def drop_panel(self, panel: QDockWidget, target: Edge | PanelDropTarget) -> None:
        """Place ``panel`` at a resolved target through the public seam."""
        if isinstance(target, Edge):
            target = PanelDropTarget.outer(target)
        if target.edge is not None:
            self._drop_at_edge(panel, target.edge)
            return
        target_panel = next(
            (candidate for candidate in self._panels if self._panel_id(candidate) == target.panel_id),
            None,
        )
        if target_panel is None or target_panel is panel or target_panel.isFloating():
            return
        position = target.position
        if position == CompassPosition.CENTER:
            panel.setFloating(False)
            self.workspace.addDockWidget(self.workspace.dockWidgetArea(target_panel), panel)
            self.workspace.tabifyDockWidget(target_panel, panel)
            panel.show()
            panel.raise_()
            return
        if position is None:
            return
        orientation = Qt.Horizontal if position in (CompassPosition.LEFT, CompassPosition.RIGHT) else Qt.Vertical
        panel.setFloating(False)
        area = self.workspace.dockWidgetArea(target_panel)
        self.workspace.addDockWidget(area, panel)
        if position in (CompassPosition.LEFT, CompassPosition.TOP):
            self.workspace.splitDockWidget(panel, target_panel, orientation)
        else:
            self.workspace.splitDockWidget(target_panel, panel, orientation)
        panel.show()

    def _drop_at_edge(self, panel: QDockWidget, edge: Edge) -> None:
        area = self._DOCK_AREAS[edge]
        panel.setFloating(False)
        self.workspace.removeDockWidget(panel)
        for corner in self._EDGE_CORNERS[edge]:
            self.workspace.setCorner(corner, area)
        self.workspace.addDockWidget(area, panel)
        panel.show()


__all__ = ["PanelDockController", "PanelDropOverlay"]
