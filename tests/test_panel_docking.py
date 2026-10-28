"""User-visible panel docking behaviour."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
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
    panel_preview_rect,
    resolve_drop_target,
    resolve_outer_edge_target,
    top_level_layout_members,
)
from blab.ui.main_window_widgets import DockTitleBar


class DockWorkspace:
    """Small public-seam harness for native dock layout tests."""

    def __init__(self, width: int = 900, height: int = 600):
        self.window = QMainWindow()
        self.window.resize(width, height)
        self._controllers: list[PanelDockController] = []

    def add_panel(self, panel_id: str) -> QDockWidget:
        panel = QDockWidget(panel_id.replace("-", " ").title(), self.window)
        panel.setObjectName(panel_id)
        panel.setWidget(QWidget())
        return panel

    def controller(self, *panels: QDockWidget) -> PanelDockController:
        controller = PanelDockController(self.window, panels)
        self._controllers.append(controller)
        return controller


@pytest.fixture
def dock_workspace(qapp):
    harness = DockWorkspace()
    yield harness
    harness.window.close()
    harness.window.deleteLater()
    qapp.processEvents()


def test_cursor_near_each_workspace_edge_resolves_to_that_edge() -> None:
    workspace = Rect(100, 200, 800, 600)

    assert resolve_outer_edge_target(Point(101, 500), workspace) == Edge.LEFT
    assert resolve_outer_edge_target(Point(899, 500), workspace) == Edge.RIGHT
    assert resolve_outer_edge_target(Point(500, 201), workspace) == Edge.TOP
    assert resolve_outer_edge_target(Point(500, 799), workspace) == Edge.BOTTOM


def test_cursor_outside_edges_or_away_from_an_edge_has_no_target() -> None:
    workspace = Rect(100, 200, 800, 600)

    assert resolve_outer_edge_target(Point(99, 500), workspace) is None
    assert resolve_outer_edge_target(Point(500, 400), workspace) is None


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


def test_side_drop_preview_shows_the_new_panels_final_equal_share() -> None:
    panels = {
        "first": Rect(0, 0, 600, 600),
        "second": Rect(600, 0, 300, 600),
    }

    assert panel_preview_rect(panels, "second", CompassPosition.RIGHT) == Rect(
        600,
        0,
        300,
        600,
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


def test_public_drop_entry_point_docks_at_outer_edge_and_state_round_trips(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    controller = dock_workspace.controller(first, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.LEFT)
    qapp.processEvents()

    assert workspace.dockWidgetArea(moved) == Qt.LeftDockWidgetArea
    state = workspace.saveState()
    assert not state.isEmpty()
    assert workspace.restoreState(state)


def test_public_drop_entry_point_places_panel_on_each_side(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    targets: list[tuple[CompassPosition, Callable[[QDockWidget, QDockWidget], bool]]] = [
        (CompassPosition.LEFT, lambda moved, target: moved.x() < target.x()),
        (CompassPosition.RIGHT, lambda moved, target: moved.x() > target.x()),
        (CompassPosition.TOP, lambda moved, target: moved.y() < target.y()),
        (CompassPosition.BOTTOM, lambda moved, target: moved.y() > target.y()),
    ]

    for index, (position, is_on_requested_side) in enumerate(targets):
        target = dock_workspace.add_panel(f"target-{index}")
        moved = dock_workspace.add_panel(f"moved-{index}")
        workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
        workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
        controller = dock_workspace.controller(target, moved)
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


def test_side_drop_equalises_three_members_in_the_affected_row(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    second = dock_workspace.add_panel("second")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.addDockWidget(Qt.BottomDockWidgetArea, moved)
    controller = dock_workspace.controller(first, second, moved)
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


def test_dragging_panel_out_of_row_equalises_remaining_members(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    second = dock_workspace.add_panel("second")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, moved, Qt.Horizontal)
    controller = dock_workspace.controller(first, second, moved)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second, moved], [500, 275, 125], Qt.Horizontal)
    qapp.processEvents()

    controller.drop_panel(moved, Edge.BOTTOM)
    qapp.processEvents()

    assert abs(first.width() - second.width()) <= 2


def test_floating_panel_out_of_row_equalises_remaining_members(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    second = dock_workspace.add_panel("second")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, moved, Qt.Horizontal)
    controller = dock_workspace.controller(first, second, moved)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second, moved], [500, 275, 125], Qt.Horizontal)
    qapp.processEvents()

    controller.finish_drag(moved, workspace.mapToGlobal(QPoint(-100, -100)), None)
    qapp.processEvents()

    assert moved.isFloating()
    assert abs(first.width() - second.width()) <= 2


def test_closing_or_hiding_panel_does_not_equalise_remaining_members(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    second = dock_workspace.add_panel("second")
    closed = dock_workspace.add_panel("closed")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, closed, Qt.Horizontal)
    dock_workspace.controller(first, second, closed)
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
    assert all(
        abs(actual - tuned) <= 2
        for actual, tuned in zip((first.width(), second.width(), closed.width()), tuned_widths, strict=True)
    )

    closed.setVisible(False)
    qapp.processEvents()

    assert abs(first.width() - second.width()) > 20


def test_dragging_tab_out_does_not_resize_group_that_stays_in_row(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    dragged_tab = dock_workspace.add_panel("dragged-tab")
    remaining_tab = dock_workspace.add_panel("remaining-tab")
    second = dock_workspace.add_panel("second")
    third = dock_workspace.add_panel("third")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged_tab)
    workspace.splitDockWidget(dragged_tab, second, Qt.Horizontal)
    workspace.splitDockWidget(second, third, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, remaining_tab)
    workspace.tabifyDockWidget(dragged_tab, remaining_tab)
    dragged_tab.raise_()
    controller = dock_workspace.controller(dragged_tab, remaining_tab, second, third)
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


def test_dragging_registered_first_tab_into_same_row_equalises_remaining_group(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    dragged = dock_workspace.add_panel("dragged")
    remaining_tab = dock_workspace.add_panel("remaining-tab")
    target = dock_workspace.add_panel("target")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged)
    workspace.splitDockWidget(dragged, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, remaining_tab)
    workspace.tabifyDockWidget(dragged, remaining_tab)
    dragged.raise_()
    controller = dock_workspace.controller(dragged, remaining_tab, target)
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


def test_bottom_side_drop_equalises_heights_without_resizing_outside_column(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    generator = dock_workspace.add_panel("generator")
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, generator)
    workspace.splitDockWidget(generator, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(generator, target, moved)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([generator, target], [250, 650], Qt.Horizontal)
    qapp.processEvents()
    generator_width = generator.width()

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.BOTTOM))
    qapp.processEvents()

    assert abs(target.height() - moved.height()) <= 2
    assert abs(generator.width() - generator_width) <= 2


def test_public_drop_entry_point_tabs_panel_with_target(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    controller = dock_workspace.controller(target, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.CENTER))
    qapp.processEvents()

    assert moved in workspace.tabifiedDockWidgets(target)


def test_tab_group_counts_as_one_member_when_side_drop_is_equalised(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    first_tab = dock_workspace.add_panel("first-tab")
    active_tab = dock_workspace.add_panel("active-tab")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first_tab)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, active_tab)
    workspace.tabifyDockWidget(first_tab, active_tab)
    active_tab.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(first_tab, active_tab, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("active-tab", CompassPosition.RIGHT))
    qapp.processEvents()

    assert first_tab in workspace.tabifiedDockWidgets(active_tab)
    assert moved.width() >= workspace.width() * 0.45


def test_tab_drop_does_not_equalise_existing_panel_sizes(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    generator = dock_workspace.add_panel("generator")
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, generator)
    workspace.splitDockWidget(generator, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(generator, target, moved)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([generator, target], [250, 650], Qt.Horizontal)
    qapp.processEvents()
    original_widths = (generator.width(), target.width())

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.CENTER))
    qapp.processEvents()

    assert (generator.width(), target.width()) == original_widths


def test_tab_drop_from_docked_row_does_not_equalise_departed_panels(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    workspace.resize(1200, 600)
    first = dock_workspace.add_panel("first")
    second = dock_workspace.add_panel("second")
    moved = dock_workspace.add_panel("moved")
    target = dock_workspace.add_panel("target")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.splitDockWidget(second, moved, Qt.Horizontal)
    workspace.splitDockWidget(moved, target, Qt.Horizontal)
    controller = dock_workspace.controller(first, second, moved, target)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([first, second, moved, target], [600, 300, 200, 100], Qt.Horizontal)
    qapp.processEvents()
    source_ratio = first.width() / second.width()

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.CENTER))
    qapp.processEvents()

    assert moved in workspace.tabifiedDockWidgets(target)
    assert first.width() > second.width() > target.width()
    assert abs(first.width() / second.width() - source_ratio) <= 0.02


def test_side_edge_drop_is_outermost_and_spans_workspace_height(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    top = dock_workspace.add_panel("top")
    top_content = QWidget()
    top_content.setMinimumSize(100, 100)
    top.setWidget(top_content)
    moved = dock_workspace.add_panel("moved")
    moved_content = QWidget()
    moved_content.setMinimumSize(100, 100)
    moved.setWidget(moved_content)
    workspace.addDockWidget(Qt.TopDockWidgetArea, top)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    controller = dock_workspace.controller(top, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.LEFT)
    qapp.processEvents()

    assert moved.height() >= workspace.height() * 0.8


def test_bottom_edge_drop_equalises_the_top_level_rows(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    existing = dock_workspace.add_panel("existing")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, existing)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(existing, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.BOTTOM)
    qapp.processEvents()

    assert abs(existing.height() - moved.height()) <= 2


def test_side_edge_drop_equalises_all_top_level_columns(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    second = dock_workspace.add_panel("second")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, second, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(first, second, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, Edge.LEFT)
    qapp.processEvents()

    widths = [first.width(), second.width(), moved.width()]
    assert max(widths) - min(widths) <= 2


def test_cancel_and_release_on_current_panel_leave_native_layout_state_unchanged(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    panel = dock_workspace.add_panel("panel")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, panel)
    controller = dock_workspace.controller(panel)
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


def test_outer_edge_target_inside_dragged_panels_old_rectangle_still_docks(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    dragged = dock_workspace.add_panel("dragged")
    other = dock_workspace.add_panel("other")
    workspace.addDockWidget(Qt.TopDockWidgetArea, dragged)
    workspace.splitDockWidget(dragged, other, Qt.Vertical)
    controller = dock_workspace.controller(dragged, other)
    workspace.show()
    qapp.processEvents()
    cursor = dragged.mapToGlobal(QPoint(10, dragged.height() // 2))
    assert QRect(dragged.mapToGlobal(QPoint()), dragged.size()).contains(cursor)

    controller.finish_drag(dragged, cursor, Edge.LEFT)
    qapp.processEvents()

    assert dragged.x() < other.x()
    assert dragged.height() >= workspace.height() * 0.8


def test_release_outside_targets_floats_panel_and_floating_panel_can_dock_back(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    panel = dock_workspace.add_panel("panel")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, panel)
    controller = dock_workspace.controller(panel)
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


def test_title_bar_waits_for_platform_drag_distance_and_keeps_controls_working(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    panel = dock_workspace.add_panel("panel")
    tool_action = QAction("Tool", panel)
    triggered: list[bool] = []
    tool_action.triggered.connect(lambda checked=False: triggered.append(checked))
    title_bar = DockTitleBar("Panel", panel, tool_actions=(tool_action,))
    panel.setTitleBarWidget(title_bar)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, panel)
    controller = dock_workspace.controller(panel)
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
