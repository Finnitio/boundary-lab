"""Reusable title-bar dragging and outer-edge docking for panel workspaces."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

from blab.ui.dock_targets import (
    Edge,
    Point,
    Rect,
    edge_target_rects,
    preview_rect,
    resolve_outer_edge_target,
)


def _qrect(rect: Rect) -> QRect:
    return QRect(rect.x, rect.y, rect.width, rect.height)


class PanelDropOverlay(QWidget):
    """Workspace overlay that paints drop targets and owns an active drag."""

    def __init__(self, controller: PanelDockController, workspace: QMainWindow):
        super().__init__(workspace)
        self._controller = controller
        self._dragged_panel: QDockWidget | None = None
        self._hovered_edge: Edge | None = None
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
        self._hovered_edge = None
        self.hide()

    def _update_hover(self, global_cursor: QPoint) -> None:
        local = self.mapFromGlobal(global_cursor)
        workspace = Rect(0, 0, self.width(), self.height())
        self._hovered_edge = resolve_outer_edge_target(Point(local.x(), local.y()), workspace)
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
        edge = self._hovered_edge
        self.end()
        self._controller.finish_drag(panel, cursor, edge)
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
        if self._hovered_edge is not None:
            painter.fillRect(_qrect(preview_rect(workspace, self._hovered_edge)), preview_fill)
        for target in edge_target_rects(workspace).values():
            rect = _qrect(target).adjusted(5, 5, -5, -5)
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

    def register_panel(self, panel: QDockWidget) -> None:
        """Enable custom dragging for one panel's title bar."""
        title_bar = panel.titleBarWidget()
        if title_bar is not None and hasattr(title_bar, "set_dock_controller"):
            title_bar.set_dock_controller(self)

    def start_drag(self, panel: QDockWidget, global_cursor: QPoint) -> None:
        self._dragged_panel = panel
        self.overlay.begin(panel, global_cursor)

    def cancel_drag(self) -> None:
        """Cancel without touching the native layout."""
        self._dragged_panel = None

    def finish_drag(self, panel: QDockWidget, global_cursor: QPoint, edge: Edge | None) -> None:
        self._dragged_panel = None
        panel_rect = QRect(panel.mapToGlobal(QPoint(0, 0)), panel.size())
        if not panel.isFloating() and panel_rect.contains(global_cursor):
            return
        if edge is not None:
            self.drop_panel(panel, edge)
            return
        panel.setFloating(True)
        panel.show()
        panel.move(global_cursor - QPoint(panel.width() // 2, 12))

    def drop_panel(self, panel: QDockWidget, edge: Edge) -> None:
        """Dock ``panel`` at an outer workspace edge through the public seam."""
        area = self._DOCK_AREAS[edge]
        panel.setFloating(False)
        self.workspace.removeDockWidget(panel)
        for corner in self._EDGE_CORNERS[edge]:
            self.workspace.setCorner(corner, area)
        self.workspace.addDockWidget(area, panel)
        panel.show()


__all__ = ["PanelDockController", "PanelDropOverlay"]
