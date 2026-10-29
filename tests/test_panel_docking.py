"""User-visible panel docking behaviour."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QAction, QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QStyle, QTabBar, QWidget

from blab.ui.dock_drag import PanelDockController
from blab.ui.dock_targets import (
    CompassPosition,
    Edge,
    EqualiseAxis,
    PanelDropTarget,
    Point,
    Rect,
    aligned_layout_members,
    compass_target_rects,
    drop_target_rects,
    edge_target_rects,
    panel_preview_rect,
    resolve_drop_target,
    resolve_outer_edge_target,
    resolve_target_rects,
    target_paint_order,
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

    def show(self, qapp) -> None:
        """Show the native workspace and settle its dock layout."""
        self.window.show()
        qapp.processEvents()

    def drag_to_panel_target(
        self,
        qapp,
        controller: PanelDockController,
        moved: QDockWidget,
        target_id: str,
        position: CompassPosition,
    ) -> PanelDropTarget | None:
        """Exercise the overlay's start, move, and release path."""
        controller.start_drag(moved, self.window.mapToGlobal(self.window.rect().center()))
        target = next(group for group in controller.overlay.eligible_targets if target_id in group.member_ids)
        rect = compass_target_rects(target.rect)[position]
        local = QPoint(rect.x + rect.width // 2, rect.y + rect.height // 2)
        global_cursor = self.window.mapToGlobal(local)
        QApplication.sendEvent(
            controller.overlay,
            QMouseEvent(
                QEvent.MouseMove,
                QPointF(local),
                QPointF(global_cursor),
                Qt.NoButton,
                Qt.LeftButton,
                Qt.NoModifier,
            ),
        )
        active_target = controller.overlay.active_target
        QApplication.sendEvent(
            controller.overlay,
            QMouseEvent(
                QEvent.MouseButtonRelease,
                QPointF(local),
                QPointF(global_cursor),
                Qt.LeftButton,
                Qt.NoButton,
                Qt.NoModifier,
            ),
        )
        qapp.processEvents()
        return active_target


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


@pytest.mark.parametrize(
    "owner",
    [
        Rect(10, 20, 30, 18),
        Rect(10, 20, 2, 1),
        Rect(10, 20, 0, 0),
    ],
)
def test_compass_targets_fit_inside_dense_and_zero_sized_groups(owner: Rect) -> None:
    for target in compass_target_rects(owner).values():
        assert target.width >= 0
        assert target.height >= 0
        assert owner.x <= target.x <= target.right <= owner.right
        assert owner.y <= target.y <= target.bottom <= owner.bottom


@pytest.mark.parametrize("workspace", [Rect(5, 7, 30, 12), Rect(5, 7, 1, 1), Rect(5, 7, 0, 0)])
def test_edge_targets_have_non_negative_geometry_in_tiny_workspaces(workspace: Rect) -> None:
    for target in edge_target_rects(workspace).values():
        assert target.width >= 0
        assert target.height >= 0
        assert workspace.x <= target.x <= target.right <= workspace.right
        assert workspace.y <= target.y <= target.bottom <= workspace.bottom


def test_compass_precedes_outer_edge_and_edge_wins_elsewhere() -> None:
    workspace = Rect(0, 0, 400, 300)
    panels = {
        "edge-panel": Rect(0, 0, 120, 300),
        "dragged": Rect(120, 0, 280, 300),
        "dragged-tab": Rect(120, 0, 280, 300),
    }

    assert resolve_drop_target(Point(59, 150), workspace, panels) == PanelDropTarget.panel(
        "edge-panel",
        CompassPosition.CENTER,
    )
    assert resolve_drop_target(Point(10, 10), workspace, panels) == PanelDropTarget.outer(Edge.LEFT)
    assert (
        resolve_drop_target(
            Point(260, 150),
            workspace,
            panels,
            excluded_panel_ids={"dragged", "dragged-tab"},
        )
        is None
    )


@pytest.mark.parametrize("reverse_order", [False, True])
def test_overlapping_compasses_choose_nearest_centre_independent_of_order(reverse_order: bool) -> None:
    workspace = Rect(0, 0, 200, 100)
    entries = [("alpha", Rect(0, 0, 90, 90)), ("beta", Rect(20, 0, 90, 90))]
    panels = dict(reversed(entries) if reverse_order else entries)
    targets = drop_target_rects(workspace, panels)

    assert resolve_target_rects(Point(51, 45), targets) == PanelDropTarget.panel(
        "alpha",
        CompassPosition.CENTER,
    )
    assert resolve_target_rects(Point(58, 45), targets) == PanelDropTarget.panel(
        "beta",
        CompassPosition.CENTER,
    )
    assert resolve_target_rects(Point(55, 45), targets) == PanelDropTarget.panel(
        "alpha",
        CompassPosition.CENTER,
    )


def test_winning_compass_paints_above_edges_and_competing_compasses() -> None:
    workspace = Rect(0, 0, 200, 100)
    targets = drop_target_rects(
        workspace,
        {"alpha": Rect(0, 0, 90, 90), "beta": Rect(20, 0, 90, 90)},
    )
    active = resolve_target_rects(Point(58, 45), targets)

    order = target_paint_order(targets, active)

    assert all(target.edge is not None for target in order[:4])
    assert {target.panel_id for target in order[-5:]} == {"beta"}
    assert set(order) == set(targets)


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


def test_equalisation_members_are_rounding_tolerant_contiguous_slots() -> None:
    panels = {
        "first": Rect(0, 0, 296, 300),
        "second": Rect(302, 1, 296, 299),
        "second-tab": Rect(302, 1, 296, 299),
        "third": Rect(604, 0, 296, 300),
        "disconnected": Rect(1000, 0, 296, 300),
    }

    assert aligned_layout_members(
        panels,
        "second",
        EqualiseAxis.HORIZONTAL,
        separator_extent=6,
    ) == ("first", "second", "third")


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


def test_drag_overlay_exposes_all_targets_and_one_third_directional_preview(
    dock_workspace,
    qapp,
) -> None:
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

    groups = controller.docked_group_targets()
    second_group = next(group for group in groups if "second" in group.member_ids)
    right_rect = compass_target_rects(second_group.rect)[CompassPosition.RIGHT]
    cursor = workspace.mapToGlobal(QPoint(right_rect.x + right_rect.width // 2, right_rect.y + right_rect.height // 2))

    controller.start_drag(moved, cursor)

    expected_active = PanelDropTarget.panel(second_group.panel_id, CompassPosition.RIGHT)
    assert set(controller.overlay.target_rects) == {
        *(PanelDropTarget.outer(edge) for edge in Edge),
        *(PanelDropTarget.panel(group.panel_id, position) for group in groups for position in CompassPosition),
    }
    assert controller.overlay.active_target == expected_active
    total_left = min(group.rect.x for group in groups)
    total_right = max(group.rect.right for group in groups)
    expected_width = (total_right - total_left) // 3
    expected_preview = Rect(
        total_left + 2 * expected_width,
        second_group.rect.y,
        expected_width,
        second_group.rect.height,
    )
    assert controller.overlay.preview_rect == expected_preview

    local_cursor = workspace.mapFromGlobal(cursor)
    QApplication.sendEvent(
        controller.overlay,
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(local_cursor),
            QPointF(cursor),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    )
    qapp.processEvents()

    separator_tolerance = workspace.style().pixelMetric(QStyle.PM_DockWidgetSeparatorExtent) + 2
    assert not moved.isFloating()
    assert abs(moved.x() - expected_preview.x) <= separator_tolerance
    assert abs(moved.width() - expected_preview.width) <= separator_tolerance


def test_dense_small_workspace_keeps_compasses_fitted_and_paints_direct_hit_last(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    workspace.resize(240, 120)
    left = dock_workspace.add_panel("left")
    right = dock_workspace.add_panel("right")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, left)
    workspace.splitDockWidget(left, right, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(left, right, moved)
    workspace.show()
    qapp.processEvents()

    groups = controller.docked_group_targets()
    left_group = min(groups, key=lambda group: group.rect.x)
    left_target = compass_target_rects(left_group.rect)[CompassPosition.LEFT]
    cursor = workspace.mapToGlobal(
        QPoint(left_target.x + left_target.width // 2, left_target.y + left_target.height // 2)
    )

    controller.start_drag(moved, cursor)

    expected_active = PanelDropTarget.panel(left_group.panel_id, CompassPosition.LEFT)
    assert controller.overlay.active_target == expected_active
    assert controller.overlay.target_rects == drop_target_rects(
        Rect(0, 0, workspace.width(), workspace.height()),
        {group.panel_id: group.rect for group in groups},
    )
    for group in groups:
        for target in compass_target_rects(group.rect).values():
            assert group.rect.x <= target.x <= target.right <= group.rect.right
            assert group.rect.y <= target.y <= target.bottom <= group.rect.bottom
    assert {target.panel_id for target in controller.overlay.paint_order[-5:]} == {left_group.panel_id}

    controller.overlay.end()
    controller.cancel_drag()


def test_rendered_target_pen_never_extends_beyond_clickable_shape(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(target, moved)
    dock_workspace.show(qapp)
    group = controller.docked_group_targets()[0]
    left = compass_target_rects(group.rect)[CompassPosition.LEFT]
    cursor = workspace.mapToGlobal(QPoint(left.x + left.width // 2, left.y + left.height // 2))
    controller.start_drag(moved, cursor)

    image = QImage(workspace.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(Qt.transparent))
    controller.overlay.render(image)

    y = left.y + left.height // 2
    assert image.pixelColor(left.x - 1, y) == image.pixelColor(left.x - 4, y)

    controller.overlay.end()
    controller.cancel_drag()


def test_centre_preview_covers_the_target_groups_complete_spatial_slot(
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

    group = controller.docked_group_targets()[0]
    tab_bar = next(tab_bar for tab_bar in workspace.findChildren(QTabBar) if tab_bar.isVisible())
    tab_origin = tab_bar.mapTo(workspace, QPoint())
    complete_bottom = max(group.rect.bottom, tab_origin.y() + tab_bar.height())
    centre = compass_target_rects(group.rect)[CompassPosition.CENTER]
    cursor = workspace.mapToGlobal(QPoint(centre.x + centre.width // 2, centre.y + centre.height // 2))

    controller.start_drag(moved, cursor)

    assert controller.overlay.active_target == PanelDropTarget.panel(group.panel_id, CompassPosition.CENTER)
    assert controller.overlay.preview_rect == Rect(
        group.rect.x,
        group.rect.y,
        group.rect.width,
        complete_bottom - group.rect.y,
    )
    assert controller.overlay.preview_rect.bottom == tab_origin.y() + tab_bar.height()

    controller.overlay.end()
    controller.cancel_drag()


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
        assert moved not in workspace.tabifiedDockWidgets(target), position
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


def test_side_drop_respects_minimum_size_without_qt_warnings(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    constrained = dock_workspace.add_panel("constrained")
    constrained.widget().setMinimumWidth(500)
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, constrained)
    workspace.splitDockWidget(constrained, target, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(constrained, target, moved)
    workspace.show()
    qapp.processEvents()

    warnings: list[str] = []

    def record_warning(message_type, _context, message) -> None:
        if message_type == QtMsgType.QtWarningMsg and message != "This plugin does not support propagateSizeHints()":
            warnings.append(message)

    previous_handler = qInstallMessageHandler(record_warning)
    try:
        controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.RIGHT))
        qapp.processEvents()
    finally:
        qInstallMessageHandler(previous_handler)

    assert constrained.width() >= 500
    assert abs(target.width() - moved.width()) <= 2
    assert warnings == []


def test_moving_panel_between_runs_equalises_source_and_destination(dock_workspace, qapp) -> None:
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
    assert abs(first.height() - moved.height()) <= 2


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


def test_drag_targets_are_one_per_visible_group_independent_of_registration_order(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    dragged = dock_workspace.add_panel("dragged")
    source_sibling = dock_workspace.add_panel("source-sibling")
    inactive_target = dock_workspace.add_panel("inactive-target")
    active_target = dock_workspace.add_panel("active-target")
    standalone = dock_workspace.add_panel("standalone")
    floating = dock_workspace.add_panel("floating")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged)
    workspace.splitDockWidget(dragged, inactive_target, Qt.Horizontal)
    workspace.splitDockWidget(inactive_target, standalone, Qt.Vertical)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, source_sibling)
    workspace.tabifyDockWidget(dragged, source_sibling)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, active_target)
    workspace.tabifyDockWidget(inactive_target, active_target)
    active_target.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, floating)
    floating.setFloating(True)
    controller = dock_workspace.controller(
        floating,
        standalone,
        active_target,
        inactive_target,
        source_sibling,
        dragged,
    )
    workspace.show()
    qapp.processEvents()

    controller.start_drag(dragged, dragged.mapToGlobal(dragged.rect().center()))
    targets = controller.overlay.eligible_targets

    assert {target.member_ids for target in targets} == {
        frozenset({"source-sibling"}),
        frozenset({"inactive-target", "active-target"}),
        frozenset({"standalone"}),
    }
    source_target = next(target for target in targets if target.member_ids == {"source-sibling"})
    for position, rect in compass_target_rects(source_target.rect).items():
        cursor = Point(rect.x + rect.width // 2, rect.y + rect.height // 2)
        assert resolve_drop_target(cursor, Rect(0, 0, 900, 600), {source_target.panel_id: source_target.rect}) == (
            PanelDropTarget.panel(source_target.panel_id, position)
        )

    controller.overlay.end()
    controller.cancel_drag()

    forward_controller = dock_workspace.controller(
        dragged,
        source_sibling,
        inactive_target,
        active_target,
        standalone,
        floating,
    )
    forward_controller.start_drag(dragged, dragged.mapToGlobal(dragged.rect().center()))
    assert {
        (target.panel_id, target.member_ids, target.rect) for target in forward_controller.overlay.eligible_targets
    } == {(target.panel_id, target.member_ids, target.rect) for target in targets}
    forward_controller.overlay.end()
    forward_controller.cancel_drag()


def test_inactive_tab_with_stale_geometry_never_supplies_group_rect(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    inactive = dock_workspace.add_panel("inactive")
    active = dock_workspace.add_panel("active")
    neighbour = dock_workspace.add_panel("neighbour")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, inactive)
    workspace.splitDockWidget(inactive, neighbour, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, active)
    workspace.tabifyDockWidget(inactive, active)
    active.raise_()
    controller = dock_workspace.controller(inactive, active, neighbour)
    dock_workspace.show(qapp)
    active_origin = active.mapTo(workspace, QPoint())
    visible_rect = Rect(active_origin.x(), active_origin.y(), active.width(), active.height())

    assert active.visibleRegion().isEmpty() is False
    assert inactive.visibleRegion().isEmpty()
    assert inactive.geometry() != active.geometry()

    group = next(group for group in controller.docked_group_targets() if "active" in group.member_ids)

    assert group.rect == visible_rect


def test_standalone_source_has_no_target_and_floating_source_can_target_docked_group(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    docked = dock_workspace.add_panel("docked")
    standalone = dock_workspace.add_panel("standalone")
    floating = dock_workspace.add_panel("floating")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, docked)
    workspace.splitDockWidget(docked, standalone, Qt.Horizontal)
    workspace.addDockWidget(Qt.RightDockWidgetArea, floating)
    floating.setFloating(True)
    controller = dock_workspace.controller(floating, standalone, docked)
    workspace.show()
    qapp.processEvents()

    controller.start_drag(standalone, standalone.mapToGlobal(standalone.rect().center()))
    assert {target.member_ids for target in controller.overlay.eligible_targets} == {frozenset({"docked"})}
    controller.overlay.end()
    controller.cancel_drag()

    controller.start_drag(floating, workspace.mapToGlobal(workspace.rect().center()))
    assert {target.member_ids for target in controller.overlay.eligible_targets} == {
        frozenset({"docked"}),
        frozenset({"standalone"}),
    }
    controller.overlay.end()
    controller.cancel_drag()


@pytest.mark.parametrize(
    ("position", "is_on_requested_side"),
    [
        (CompassPosition.LEFT, lambda moved, target: moved.x() < target.x()),
        (CompassPosition.RIGHT, lambda moved, target: moved.x() > target.x()),
        (CompassPosition.TOP, lambda moved, target: moved.y() < target.y()),
        (CompassPosition.BOTTOM, lambda moved, target: moved.y() > target.y()),
    ],
)
def test_remaining_source_group_accepts_directional_drop(
    dock_workspace,
    qapp,
    position,
    is_on_requested_side,
) -> None:
    workspace = dock_workspace.window
    dragged = dock_workspace.add_panel("dragged")
    source_sibling = dock_workspace.add_panel("source-sibling")
    other = dock_workspace.add_panel("other")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged)
    workspace.splitDockWidget(dragged, other, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, source_sibling)
    workspace.tabifyDockWidget(dragged, source_sibling)
    dragged.raise_()
    controller = dock_workspace.controller(dragged, source_sibling, other)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(dragged, PanelDropTarget.panel("source-sibling", position))
    qapp.processEvents()

    assert is_on_requested_side(dragged, source_sibling)
    assert dragged not in workspace.tabifiedDockWidgets(source_sibling)


def test_centre_drop_back_on_source_group_preserves_spatial_sizes(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    dragged = dock_workspace.add_panel("dragged")
    source_sibling = dock_workspace.add_panel("source-sibling")
    other = dock_workspace.add_panel("other")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged)
    workspace.splitDockWidget(dragged, other, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, source_sibling)
    workspace.tabifyDockWidget(dragged, source_sibling)
    dragged.raise_()
    controller = dock_workspace.controller(dragged, source_sibling, other)
    workspace.show()
    qapp.processEvents()
    workspace.resizeDocks([dragged, other], [650, 250], Qt.Horizontal)
    qapp.processEvents()
    original_widths = (source_sibling.width(), other.width())

    controller.drop_panel(dragged, PanelDropTarget.panel("source-sibling", CompassPosition.CENTER))
    qapp.processEvents()

    assert dragged in workspace.tabifiedDockWidgets(source_sibling)
    assert (source_sibling.width(), other.width()) == original_widths


def test_escape_from_source_group_drag_preserves_native_layout_state(dock_workspace, qapp) -> None:
    workspace = dock_workspace.window
    dragged = dock_workspace.add_panel("dragged")
    source_sibling = dock_workspace.add_panel("source-sibling")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, dragged)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, source_sibling)
    workspace.tabifyDockWidget(dragged, source_sibling)
    dragged.raise_()
    controller = dock_workspace.controller(dragged, source_sibling)
    workspace.show()
    qapp.processEvents()
    original_state = workspace.saveState()

    controller.start_drag(dragged, dragged.mapToGlobal(dragged.rect().center()))
    controller.overlay.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))

    assert workspace.saveState() == original_state


@pytest.mark.parametrize(
    ("position", "is_on_requested_side"),
    [
        (CompassPosition.LEFT, lambda moved, target: moved.x() < target.x()),
        (CompassPosition.RIGHT, lambda moved, target: moved.x() > target.x()),
        (CompassPosition.TOP, lambda moved, target: moved.y() < target.y()),
        (CompassPosition.BOTTOM, lambda moved, target: moved.y() > target.y()),
    ],
)
def test_directional_drop_places_panel_beside_whole_tab_group(
    dock_workspace,
    qapp,
    position,
    is_on_requested_side,
) -> None:
    workspace = dock_workspace.window
    first_tab = dock_workspace.add_panel("first-tab")
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first_tab)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    workspace.tabifyDockWidget(first_tab, target)
    target.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(first_tab, target, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("target", position))
    qapp.processEvents()

    assert is_on_requested_side(moved, target)
    assert moved not in workspace.tabifiedDockWidgets(target)
    assert first_tab in workspace.tabifiedDockWidgets(target)


@pytest.mark.parametrize("tabbed_target", [False, True], ids=["standalone", "tab-group"])
@pytest.mark.parametrize(
    ("position", "axis"),
    [
        (CompassPosition.LEFT, Qt.Horizontal),
        (CompassPosition.RIGHT, Qt.Horizontal),
        (CompassPosition.TOP, Qt.Vertical),
        (CompassPosition.BOTTOM, Qt.Vertical),
    ],
)
def test_overlay_drag_places_and_sizes_panel_on_every_side_of_visible_group(
    dock_workspace,
    qapp,
    tabbed_target,
    position,
    axis,
) -> None:
    workspace = dock_workspace.window
    target = dock_workspace.add_panel("target")
    sibling = dock_workspace.add_panel("sibling")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    if tabbed_target:
        workspace.addDockWidget(Qt.LeftDockWidgetArea, sibling)
        workspace.tabifyDockWidget(target, sibling)
        target.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    panels = (target, sibling, moved) if tabbed_target else (target, moved)
    controller = dock_workspace.controller(*panels)
    dock_workspace.show(qapp)

    active_target = dock_workspace.drag_to_panel_target(qapp, controller, moved, "target", position)

    assert active_target == PanelDropTarget.panel("target", position)
    assert not moved.isFloating()
    assert moved not in workspace.tabifiedDockWidgets(target)
    if tabbed_target:
        assert sibling in workspace.tabifiedDockWidgets(target)
    if position == CompassPosition.LEFT:
        assert moved.x() < target.x()
    elif position == CompassPosition.RIGHT:
        assert moved.x() > target.x()
    elif position == CompassPosition.TOP:
        assert moved.y() < target.y()
    else:
        assert moved.y() > target.y()
    moved_size = moved.width() if axis == Qt.Horizontal else moved.height()
    target_size = target.width() if axis == Qt.Horizontal else target.height()
    if tabbed_target and axis == Qt.Vertical:
        target_size += next(tab_bar for tab_bar in workspace.findChildren(QTabBar) if tab_bar.isVisible()).height()
    assert abs(moved_size - target_size) <= 2


def test_directional_drop_beside_tab_group_equalises_three_spatial_slots(
    dock_workspace,
    qapp,
) -> None:
    workspace = dock_workspace.window
    first = dock_workspace.add_panel("first")
    first_tab = dock_workspace.add_panel("first-tab")
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first)
    workspace.splitDockWidget(first, first_tab, Qt.Horizontal)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    workspace.tabifyDockWidget(first_tab, target)
    target.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(first, first_tab, target, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.RIGHT))
    qapp.processEvents()

    widths = [first.width(), target.width(), moved.width()]
    assert max(widths) - min(widths) <= 2
    assert moved.x() > target.x()
    assert moved not in workspace.tabifiedDockWidgets(target)
    assert first_tab in workspace.tabifiedDockWidgets(target)


@pytest.mark.parametrize("position", [CompassPosition.RIGHT, CompassPosition.CENTER])
def test_tab_group_drop_state_round_trips(dock_workspace, qapp, position) -> None:
    workspace = dock_workspace.window
    first_tab = dock_workspace.add_panel("first-tab")
    target = dock_workspace.add_panel("target")
    moved = dock_workspace.add_panel("moved")
    workspace.addDockWidget(Qt.LeftDockWidgetArea, first_tab)
    workspace.addDockWidget(Qt.LeftDockWidgetArea, target)
    workspace.tabifyDockWidget(first_tab, target)
    target.raise_()
    workspace.addDockWidget(Qt.RightDockWidgetArea, moved)
    moved.setFloating(True)
    controller = dock_workspace.controller(first_tab, target, moved)
    workspace.show()
    qapp.processEvents()

    controller.drop_panel(moved, PanelDropTarget.panel("target", position))
    qapp.processEvents()

    state = workspace.saveState()
    assert not state.isEmpty()
    assert workspace.restoreState(state)


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


def test_tab_drop_from_docked_row_equalises_departed_panels(
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
    controller.drop_panel(moved, PanelDropTarget.panel("target", CompassPosition.CENTER))
    qapp.processEvents()

    assert moved in workspace.tabifiedDockWidgets(target)
    remaining_widths = [first.width(), second.width(), moved.width()]
    assert max(remaining_widths) - min(remaining_widths) <= 2


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
