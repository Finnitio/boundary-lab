"""User-visible panel docking behaviour."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QAction, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QWidget

from blab.ui.dock_drag import PanelDockController
from blab.ui.dock_targets import Edge, Point, Rect, resolve_outer_edge_target
from blab.ui.main_window_widgets import DockTitleBar


def test_cursor_near_each_workspace_edge_resolves_to_that_edge() -> None:
    workspace = Rect(100, 200, 800, 600)

    assert resolve_outer_edge_target(Point(101, 500), workspace) == Edge.LEFT
    assert resolve_outer_edge_target(Point(899, 500), workspace) == Edge.RIGHT
    assert resolve_outer_edge_target(Point(500, 201), workspace) == Edge.TOP
    assert resolve_outer_edge_target(Point(500, 799), workspace) == Edge.BOTTOM


def test_cursor_outside_edges_or_on_dragged_panels_unchanged_position_has_no_target() -> None:
    workspace = Rect(100, 200, 800, 600)
    dragged_panel = Rect(300, 300, 300, 300)

    assert resolve_outer_edge_target(Point(99, 500), workspace, dragged_panel) is None
    assert resolve_outer_edge_target(Point(500, 400), workspace, dragged_panel) is None


def test_public_drop_entry_point_docks_at_outer_edge_and_state_round_trips(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first = QDockWidget("First", workspace)
    first.setObjectName("first")
    first.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    controller = PanelDockController(workspace)
    controller.register_panel(first)
    controller.register_panel(moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.LEFT)
    qapp.processEvents()

    assert workspace.dockWidgetArea(moved) == Qt.LeftDockWidgetArea
    state = workspace.saveState()
    assert not state.isEmpty()
    assert workspace.restoreState(state)

    workspace.close()
    workspace.deleteLater()


def test_side_edge_drop_is_outermost_and_spans_workspace_height(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    top = QDockWidget("Top", workspace)
    top.setObjectName("top")
    top_content = QWidget()
    top_content.setMinimumSize(100, 100)
    top.setWidget(top_content)
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved_content = QWidget()
    moved_content.setMinimumSize(100, 100)
    moved.setWidget(moved_content)
    workspace.addDockWidget(Qt.TopDockWidgetArea, top)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    controller = PanelDockController(workspace)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.LEFT)
    qapp.processEvents()

    assert moved.height() >= workspace.height() * 0.8

    workspace.close()
    workspace.deleteLater()


def test_cancel_and_release_on_current_panel_leave_native_layout_state_unchanged(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    panel = QDockWidget("Panel", workspace)
    panel.setObjectName("panel")
    panel.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, panel)
    controller = PanelDockController(workspace)
    workspace.show()
    qapp.processEvents()
    original_state = workspace.saveState()

    cursor = panel.mapToGlobal(panel.rect().center())
    controller.start_drag(panel, cursor)
    controller.overlay.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert workspace.saveState() == original_state

    controller.finish_drag(panel, cursor, Edge.LEFT)
    assert workspace.saveState() == original_state
    assert not panel.isFloating()

    workspace.close()
    workspace.deleteLater()


def test_release_outside_targets_floats_panel_and_floating_panel_can_dock_back(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    panel = QDockWidget("Panel", workspace)
    panel.setObjectName("panel")
    panel.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, panel)
    controller = PanelDockController(workspace)
    workspace.show()
    qapp.processEvents()

    controller.finish_drag(panel, workspace.mapToGlobal(QPoint(-100, -100)), None)
    assert panel.isFloating()

    controller.start_drag(panel, workspace.mapToGlobal(workspace.rect().center()))
    assert controller.overlay.isVisible()
    controller.overlay.end()
    controller.drop_panel(panel, Edge.BOTTOM)
    qapp.processEvents()

    assert not panel.isFloating()
    assert workspace.dockWidgetArea(panel) == Qt.BottomDockWidgetArea

    workspace.close()
    workspace.deleteLater()


def test_title_bar_waits_for_platform_drag_distance_and_keeps_controls_working(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    panel = QDockWidget("Panel", workspace)
    panel.setObjectName("panel")
    panel.setWidget(QWidget())
    tool_action = QAction("Tool", panel)
    triggered: list[bool] = []
    tool_action.triggered.connect(lambda checked=False: triggered.append(checked))
    title_bar = DockTitleBar("Panel", panel, tool_actions=(tool_action,))
    panel.setTitleBarWidget(title_bar)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, panel)
    controller = PanelDockController(workspace)
    controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()

    press = QPoint(10, 10)
    press_global = title_bar.mapToGlobal(press)
    QApplication.sendEvent(
        title_bar,
        QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(press),
            QPointF(press_global),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    short_move = press + QPoint(max(1, QApplication.startDragDistance() - 1), 0)
    QApplication.sendEvent(
        title_bar,
        QMouseEvent(
            QEvent.MouseMove,
            QPointF(short_move),
            QPointF(title_bar.mapToGlobal(short_move)),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert not controller.overlay.isVisible()

    long_move = press + QPoint(QApplication.startDragDistance() + 1, 0)
    QApplication.sendEvent(
        title_bar,
        QMouseEvent(
            QEvent.MouseMove,
            QPointF(long_move),
            QPointF(title_bar.mapToGlobal(long_move)),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    assert controller.overlay.isVisible()
    controller.overlay.end()
    controller.cancel_drag()

    title_bar.tool_buttons[0].click()
    assert triggered == [False]
    title_bar.mouseDoubleClickEvent(
        QMouseEvent(
            QEvent.MouseButtonDblClick,
            QPointF(press),
            QPointF(press_global),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert panel.isFloating()

    workspace.close()
    workspace.deleteLater()
