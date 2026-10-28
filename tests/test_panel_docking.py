"""User-visible panel docking behaviour."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QAction, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QWidget

from blab.ui.dock_drag import PanelDockController
from blab.ui.dock_targets import (
    CompassPosition,
    Edge,
    EqualiseAxis,
    PanelDropTarget,
    Point,
    Rect,
    aligned_layout_members,
    resolve_drop_target,
    resolve_outer_edge_target,
    top_level_layout_members,
)
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


def test_cursor_resolves_each_compass_target_and_centre_over_panel() -> None:
    workspace = Rect(0, 0, 900, 600)
    panels = {"target": Rect(200, 100, 480, 400)}

    expected = {
        Point(376, 300): CompassPosition.LEFT,
        Point(504, 300): CompassPosition.RIGHT,
        Point(440, 236): CompassPosition.TOP,
        Point(440, 364): CompassPosition.BOTTOM,
        Point(440, 300): CompassPosition.CENTER,
    }
    for cursor, position in expected.items():
        assert resolve_drop_target(cursor, workspace, panels) == PanelDropTarget.panel("target", position)


def test_outer_edge_precedes_compass_and_dragged_group_is_not_a_target() -> None:
    workspace = Rect(0, 0, 400, 300)
    panels = {
        "edge-panel": Rect(0, 0, 120, 300),
        "dragged": Rect(120, 0, 280, 300),
        "dragged-tab": Rect(120, 0, 280, 300),
    }

    assert resolve_drop_target(Point(59, 150), workspace, panels) == PanelDropTarget.outer(Edge.LEFT)
    assert (
        resolve_drop_target(
            Point(260, 150),
            workspace,
            panels,
            excluded_panel_ids={"dragged", "dragged-tab"},
        )
        is None
    )


def test_equalisation_members_are_the_logical_groups_aligned_with_the_drop() -> None:
    panels = {
        "generator": Rect(0, 0, 200, 600),
        "plot-a": Rect(200, 0, 350, 300),
        "plot-a-tab": Rect(200, 0, 350, 300),
        "plot-b": Rect(550, 0, 350, 300),
        "lower-plot": Rect(200, 300, 350, 300),
    }

    assert aligned_layout_members(panels, "plot-a", EqualiseAxis.HORIZONTAL) == (
        "plot-a",
        "plot-b",
    )
    assert aligned_layout_members(panels, "plot-a", EqualiseAxis.VERTICAL) == (
        "plot-a",
        "lower-plot",
    )


def test_equalisation_uses_remaining_tab_as_group_representative() -> None:
    panels = {
        "dragged-tab": Rect(0, 0, 600, 600),
        "remaining-tab": Rect(0, 0, 600, 600),
        "target": Rect(600, 0, 300, 600),
    }
    panels.pop("dragged-tab")

    assert aligned_layout_members(panels, "target", EqualiseAxis.HORIZONTAL) == (
        "remaining-tab",
        "target",
    )


def test_outer_edge_members_collapse_panels_and_tabs_in_the_same_column() -> None:
    panels = {
        "generator": Rect(0, 0, 200, 600),
        "top-plot": Rect(200, 0, 700, 300),
        "top-plot-tab": Rect(200, 0, 700, 300),
        "bottom-plot": Rect(200, 300, 700, 300),
    }

    assert top_level_layout_members(panels, EqualiseAxis.HORIZONTAL) == (
        "generator",
        "top-plot",
    )


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


def test_public_drop_entry_point_places_panel_on_each_side(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    controller = PanelDockController(workspace)
    targets: list[tuple[CompassPosition, Callable[[QDockWidget, QDockWidget], bool]]] = [
        (CompassPosition.LEFT, lambda moved, target: moved.x() < target.x()),
        (CompassPosition.RIGHT, lambda moved, target: moved.x() > target.x()),
        (CompassPosition.TOP, lambda moved, target: moved.y() < target.y()),
        (CompassPosition.BOTTOM, lambda moved, target: moved.y() > target.y()),
    ]

    for index, (position, is_on_requested_side) in enumerate(targets):
        target = QDockWidget(f"Target {index}", workspace)
        target.setObjectName(f"target-{index}")
        target.setWidget(QWidget())
        moved = QDockWidget(f"Moved {index}", workspace)
        moved.setObjectName(f"moved-{index}")
        moved.setWidget(QWidget())
        workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
        workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
        controller.register_panel(target)
        controller.register_panel(moved)
        workspace.show()
        qapp.processEvents()

        controller.drop_panel(moved, PanelDropTarget.panel(target.objectName(), position))
        qapp.processEvents()

        assert is_on_requested_side(moved, target), position
        workspace.removeDockWidget(moved)
        workspace.removeDockWidget(target)
        moved.deleteLater()
        target.deleteLater()
        qapp.processEvents()

    workspace.close()
    workspace.deleteLater()


def test_side_drop_equalises_three_members_in_the_affected_row(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first = QDockWidget("First", workspace)
    first.setObjectName("first")
    first.setWidget(QWidget())
    second = QDockWidget("Second", workspace)
    second.setObjectName("second")
    second.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.addDockWidget(Qt.BottomDockWidgetArea, moved)
    controller = PanelDockController(workspace)
    for panel in (first, second, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second], [600, 300], Qt.Horizontal)
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("second", CompassPosition.RIGHT))
    qapp.processEvents()

    widths = [first.width(), second.width(), moved.width()]
    assert max(widths) - min(widths) <= 2

    workspace.resizeDocks([first, second, moved], [450, 300, 150], Qt.Horizontal)
    qapp.processEvents()
    user_widths = [first.width(), second.width(), moved.width()]
    qapp.processEvents()
    assert first.width() > second.width() > moved.width()
    assert [first.width(), second.width(), moved.width()] == user_widths

    workspace.close()
    workspace.deleteLater()


def test_dragging_panel_out_of_row_equalises_remaining_members(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first = QDockWidget("First", workspace)
    first.setObjectName("first")
    first.setWidget(QWidget())
    second = QDockWidget("Second", workspace)
    second.setObjectName("second")
    second.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, moved, Qt.Horizontal)
    controller = PanelDockController(workspace)
    for panel in (first, second, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second, moved], [500, 275, 125], Qt.Horizontal)
    qapp.processEvents()

    controller.drop_panel(moved, Edge.BOTTOM)
    qapp.processEvents()

    assert abs(first.width() - second.width()) <= 2

    workspace.close()
    workspace.deleteLater()


def test_floating_panel_out_of_row_equalises_remaining_members(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first = QDockWidget("First", workspace)
    first.setObjectName("first")
    first.setWidget(QWidget())
    second = QDockWidget("Second", workspace)
    second.setObjectName("second")
    second.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, moved, Qt.Horizontal)
    controller = PanelDockController(workspace)
    for panel in (first, second, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second, moved], [500, 275, 125], Qt.Horizontal)
    qapp.processEvents()

    controller.finish_drag(moved, workspace.mapToGlobal(QPoint(-100, -100)), None)
    qapp.processEvents()

    assert moved.isFloating()
    assert abs(first.width() - second.width()) <= 2

    workspace.close()
    workspace.deleteLater()


def test_closing_or_hiding_panel_does_not_equalise_remaining_members(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first = QDockWidget("First", workspace)
    first.setObjectName("first")
    first.setWidget(QWidget())
    second = QDockWidget("Second", workspace)
    second.setObjectName("second")
    second.setWidget(QWidget())
    closed = QDockWidget("Closed", workspace)
    closed.setObjectName("closed")
    closed.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, closed, Qt.Horizontal)
    controller = PanelDockController(workspace)
    for panel in (first, second, closed):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second, closed], [500, 275, 125], Qt.Horizontal)
    qapp.processEvents()
    tuned_widths = (first.width(), second.width(), closed.width())

    closed.close()
    qapp.processEvents()

    assert abs(first.width() - second.width()) > 20
    closed.show()
    qapp.processEvents()
    assert all(abs(actual - tuned) <= 2 for actual, tuned in zip(
        (first.width(), second.width(), closed.width()), tuned_widths, strict=True
    ))

    closed.setVisible(False)
    qapp.processEvents()

    assert abs(first.width() - second.width()) > 20

    workspace.close()
    workspace.deleteLater()


def test_dragging_tab_out_does_not_resize_group_that_stays_in_row(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    dragged_tab = QDockWidget("Dragged tab", workspace)
    dragged_tab.setObjectName("dragged-tab")
    dragged_tab.setWidget(QWidget())
    remaining_tab = QDockWidget("Remaining tab", workspace)
    remaining_tab.setObjectName("remaining-tab")
    remaining_tab.setWidget(QWidget())
    second = QDockWidget("Second", workspace)
    second.setObjectName("second")
    second.setWidget(QWidget())
    third = QDockWidget("Third", workspace)
    third.setObjectName("third")
    third.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged_tab)
    workspace.splitDockWidget(dragged_tab, second, Qt.Horizontal)
    workspace.splitDockWidget(second, third, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, remaining_tab)
    workspace.tabifyDockWidget(dragged_tab, remaining_tab)
    dragged_tab.raise_()
    controller = PanelDockController(workspace)
    for panel in (dragged_tab, remaining_tab, second, third):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([dragged_tab, second, third], [500, 275, 125], Qt.Horizontal)
    qapp.processEvents()
    tuned_widths = (dragged_tab.width(), second.width(), third.width())
    remaining_tab.setGeometry(dragged_tab.geometry())
    second.setGeometry(second.x(), dragged_tab.y(), second.width(), dragged_tab.height())
    third.setGeometry(third.x(), dragged_tab.y(), third.width(), dragged_tab.height())

    controller.finish_drag(dragged_tab, workspace.mapToGlobal(QPoint(-100, -100)), None)
    qapp.processEvents()

    assert dragged_tab.isFloating()
    assert (remaining_tab.width(), second.width(), third.width()) == tuned_widths

    workspace.close()
    workspace.deleteLater()


def test_dragging_registered_first_tab_into_same_row_equalises_remaining_group(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    dragged = QDockWidget("Dragged", workspace)
    dragged.setObjectName("dragged")
    dragged.setWidget(QWidget())
    remaining_tab = QDockWidget("Remaining tab", workspace)
    remaining_tab.setObjectName("remaining-tab")
    remaining_tab.setWidget(QWidget())
    target = QDockWidget("Target", workspace)
    target.setObjectName("target")
    target.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged)
    workspace.splitDockWidget(dragged, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, remaining_tab)
    workspace.tabifyDockWidget(dragged, remaining_tab)
    dragged.raise_()
    controller = PanelDockController(workspace)
    for panel in (dragged, remaining_tab, target):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([dragged, target], [600, 300], Qt.Horizontal)
    qapp.processEvents()
    # The offscreen plugin retains stale geometry for inactive tabs. Normalize
    # the logical row so this exercises registration-order representative choice.
    remaining_tab.setGeometry(dragged.geometry())
    target.setGeometry(target.x(), dragged.y(), target.width(), dragged.height())

    controller.drop_panel(dragged, PanelDropTarget.panel("target", CompassPosition.RIGHT))
    qapp.processEvents()

    widths = [remaining_tab.width(), target.width(), dragged.width()]
    assert max(widths) - min(widths) <= 2

    workspace.close()
    workspace.deleteLater()


def test_bottom_side_drop_equalises_heights_without_resizing_outside_column(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    generator = QDockWidget("Generator", workspace)
    generator.setObjectName("generator")
    generator.setWidget(QWidget())
    target = QDockWidget("Target", workspace)
    target.setObjectName("target")
    target.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, generator)
    workspace.splitDockWidget(generator, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = PanelDockController(workspace)
    for panel in (generator, target, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([generator, target], [250, 650], Qt.Horizontal)
    qapp.processEvents()
    generator_width = generator.width()

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.BOTTOM))
    qapp.processEvents()

    assert abs(target.height() - moved.height()) <= 2
    assert abs(generator.width() - generator_width) <= 2

    workspace.close()
    workspace.deleteLater()


def test_public_drop_entry_point_tabs_panel_with_target(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    target = QDockWidget("Target", workspace)
    target.setObjectName("target")
    target.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    controller = PanelDockController(workspace)
    controller.register_panel(target)
    controller.register_panel(moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.CENTER))
    qapp.processEvents()

    assert moved in workspace.tabifiedDockWidgets(target)

    workspace.close()
    workspace.deleteLater()


def test_tab_group_counts_as_one_member_when_side_drop_is_equalised(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first_tab = QDockWidget("First tab", workspace)
    first_tab.setObjectName("first-tab")
    first_tab.setWidget(QWidget())
    active_tab = QDockWidget("Active tab", workspace)
    active_tab.setObjectName("active-tab")
    active_tab.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first_tab)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, active_tab)
    workspace.tabifyDockWidget(first_tab, active_tab)
    active_tab.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = PanelDockController(workspace)
    for panel in (first_tab, active_tab, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("active-tab", CompassPosition.RIGHT))
    qapp.processEvents()

    assert first_tab in workspace.tabifiedDockWidgets(active_tab)
    assert moved.width() >= workspace.width() * 0.45

    workspace.close()
    workspace.deleteLater()


def test_tab_drop_does_not_equalise_existing_panel_sizes(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    generator = QDockWidget("Generator", workspace)
    generator.setObjectName("generator")
    generator.setWidget(QWidget())
    target = QDockWidget("Target", workspace)
    target.setObjectName("target")
    target.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, generator)
    workspace.splitDockWidget(generator, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = PanelDockController(workspace)
    for panel in (generator, target, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([generator, target], [250, 650], Qt.Horizontal)
    qapp.processEvents()
    original_widths = (generator.width(), target.width())

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.CENTER))
    qapp.processEvents()

    assert (generator.width(), target.width()) == original_widths

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


def test_bottom_edge_drop_equalises_the_top_level_rows(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    existing = QDockWidget("Existing", workspace)
    existing.setObjectName("existing")
    existing.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, existing)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = PanelDockController(workspace)
    controller.register_panel(existing)
    controller.register_panel(moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.BOTTOM)
    qapp.processEvents()

    assert abs(existing.height() - moved.height()) <= 2

    workspace.close()
    workspace.deleteLater()


def test_side_edge_drop_equalises_all_top_level_columns(qapp) -> None:
    workspace = QMainWindow()
    workspace.resize(900, 600)
    first = QDockWidget("First", workspace)
    first.setObjectName("first")
    first.setWidget(QWidget())
    second = QDockWidget("Second", workspace)
    second.setObjectName("second")
    second.setWidget(QWidget())
    moved = QDockWidget("Moved", workspace)
    moved.setObjectName("moved")
    moved.setWidget(QWidget())
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = PanelDockController(workspace)
    for panel in (first, second, moved):
        controller.register_panel(panel)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.LEFT)
    qapp.processEvents()

    widths = [first.width(), second.width(), moved.width()]
    assert max(widths) - min(widths) <= 2

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
