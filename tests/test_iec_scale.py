import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from blab.spinorama import SpinoramaCurves
from blab.ui.max_spl_plot import MaxSplCanvas
from blab.ui.plot_scale import iec_axes_box
from blab.ui.plots import OnAxisResponseCanvas, PlotAxisLimits, SpinoramaCanvas

_APP = QApplication.instance() or QApplication([])


def test_default_spl_limits_on_a_wide_area_give_a_two_to_three_box_centred_horizontally() -> None:
    # 50 dB over 20 Hz to 20 kHz: (50 / 25) / 3 decades = 2/3.
    box = iec_axes_box((1.0, 0.5, 9.0, 4.0), (20.0, 20_000.0), (-40.0, 10.0))

    x0, y0, width, height = box
    assert height == pytest.approx(4.0)
    assert width == pytest.approx(6.0)
    assert x0 == pytest.approx(2.5)
    assert y0 == pytest.approx(0.5)


def test_tall_area_is_filled_in_width_and_centred_vertically() -> None:
    # 30 dB over 100 Hz to 10 kHz: (30 / 25) / 2 decades = 0.6.
    x0, y0, width, height = iec_axes_box((0.0, 0.0, 5.0, 10.0), (100.0, 10_000.0), (60.0, 90.0))

    assert (x0, width) == pytest.approx((0.0, 5.0))
    assert height == pytest.approx(3.0)
    assert y0 == pytest.approx(3.5)


@pytest.mark.parametrize(
    ("x_limits", "y_limits"),
    [((1000.0, 1000.0), (-40.0, 10.0)), ((0.0, 1000.0), (-40.0, 10.0)), ((20.0, 20_000.0), (5.0, 5.0))],
)
def test_limits_without_a_ratio_leave_the_available_box_unchanged(x_limits, y_limits) -> None:
    assert iec_axes_box((1.0, 2.0, 3.0, 4.0), x_limits, y_limits) == (1.0, 2.0, 3.0, 4.0)


# --- Canvas level -----------------------------------------------------------


def _canvas_box_inches(canvas) -> tuple[float, float, float, float]:
    canvas.figure.canvas.draw()
    fig_w, fig_h = canvas.figure.get_size_inches()
    position = canvas.axes.get_position()
    return position.x0 * fig_w, position.y0 * fig_h, position.width * fig_w, position.height * fig_h


def _shown(canvas, width: int = 900, height: int = 420):
    canvas.resize(width, height)
    canvas.show()
    _APP.processEvents()
    return canvas


_FREQS = np.asarray([20.0, 1000.0, 20_000.0], dtype=np.float32)


def _spinorama() -> SpinoramaCanvas:
    canvas = SpinoramaCanvas()
    canvas.update_curves(
        SpinoramaCurves(
            freq_hz=_FREQS,
            on_axis_db=np.asarray([0.0, 0.0, 0.0]),
            listening_window_db=np.asarray([-1.0, -1.0, -1.0]),
            early_reflections_db=np.asarray([-2.0, -2.0, -2.0]),
            sound_power_db=np.asarray([-3.0, -3.0, -3.0]),
            estimated_in_room_db=np.asarray([-2.5, -2.5, -2.5]),
            early_reflections_di_db=np.asarray([2.0, 2.0, 2.0]),
            sound_power_di_db=np.asarray([3.0, 3.0, 3.0]),
        )
    )
    return canvas


def _on_axis() -> OnAxisResponseCanvas:
    canvas = OnAxisResponseCanvas()
    response = np.asarray([[80.0, 81.0, 80.0], [82.0, 83.0, 82.0], [84.0, 85.0, 84.0]], dtype=np.float32)
    canvas.update_plot(_FREQS, np.asarray([-10.0, 0.0, 10.0], dtype=np.float32), response)
    return canvas


def _max_spl() -> MaxSplCanvas:
    canvas = MaxSplCanvas()
    canvas.update_plot(_FREQS, np.asarray(["LF"]), np.asarray([[100.0, 110.0, 105.0]], dtype=np.float32))
    return canvas


@pytest.fixture(params=[_spinorama, _on_axis, _max_spl], ids=["spinorama", "on_axis", "max_spl"])
def iec_canvas(request):
    canvas = request.param()
    yield _shown(canvas)
    canvas.close()
    canvas.deleteLater()


def test_toggle_is_an_unchecked_checkable_action_labelled_25_db_per_decade(iec_canvas) -> None:
    action = iec_canvas.iec_scale_action
    assert action.text() == "25 dB/dec"
    assert action.isCheckable()
    assert not action.isChecked()


def test_default_limits_give_a_two_to_three_box_without_changing_the_y_span(iec_canvas) -> None:
    y_limits = iec_canvas.axes.get_ylim()
    assert iec_canvas.axes.get_xlim() == pytest.approx((20.0, 20_000.0))
    assert y_limits[1] - y_limits[0] == pytest.approx(50.0)

    iec_canvas.iec_scale_action.setChecked(True)
    _, _, width, height = _canvas_box_inches(iec_canvas)

    assert height / width == pytest.approx(2.0 / 3.0, rel=1e-6)
    assert iec_canvas.axes.get_ylim() == pytest.approx(y_limits)


def test_ratio_follows_manual_limits(iec_canvas) -> None:
    iec_canvas.iec_scale_action.setChecked(True)
    iec_canvas.set_axis_limits(PlotAxisLimits(100.0, 10_000.0, 40.0, 70.0))
    _, _, width, height = _canvas_box_inches(iec_canvas)

    # 30 dB over two decades: (30 / 25) / 2 = 0.6.
    assert height / width == pytest.approx(0.6, rel=1e-6)
    assert iec_canvas.axes.get_ylim() == pytest.approx((40.0, 70.0))


@pytest.mark.parametrize("size", [(500, 700), (1200, 300)])
def test_ratio_holds_after_a_resize(iec_canvas, size) -> None:
    iec_canvas.iec_scale_action.setChecked(True)
    iec_canvas.resize(*size)
    _APP.processEvents()
    _, _, width, height = _canvas_box_inches(iec_canvas)

    assert height / width == pytest.approx(2.0 / 3.0, rel=1e-6)


@pytest.mark.parametrize("size", [(500, 700), (1200, 300)])
def test_box_is_centred_in_the_adaptive_area_with_decorations_outside(iec_canvas, size) -> None:
    iec_canvas.resize(*size)
    _APP.processEvents()
    adaptive = _canvas_box_inches(iec_canvas)
    iec_canvas.iec_scale_action.setChecked(True)
    x0, y0, width, height = _canvas_box_inches(iec_canvas)

    ax0, ay0, awidth, aheight = adaptive
    assert x0 + width / 2 == pytest.approx(ax0 + awidth / 2)
    assert y0 + height / 2 == pytest.approx(ay0 + aheight / 2)
    assert width <= awidth + 1e-9 and height <= aheight + 1e-9
    assert max(width / awidth, height / aheight) == pytest.approx(1.0)

    renderer = iec_canvas.figure.canvas.get_renderer()
    axes_box = iec_canvas.axes.get_window_extent(renderer)
    decorations = [*iec_canvas.axes.get_xticklabels(), *iec_canvas.axes.get_yticklabels()]
    decorations += [iec_canvas.axes.xaxis.label, iec_canvas.axes.yaxis.label]
    secondary = iec_canvas.secondary_axes
    if secondary is not None and secondary.get_visible():
        decorations += [*secondary.get_yticklabels(), secondary.yaxis.label]
    legend = iec_canvas.axes.get_legend()
    if legend is not None and legend.get_visible() and isinstance(iec_canvas, SpinoramaCanvas):
        decorations.append(legend)
    for artist in decorations:
        if not artist.get_visible() or not getattr(artist, "get_text", lambda: "x")():
            continue
        extent = artist.get_window_extent(renderer)
        overlap_w = min(extent.x1, axes_box.x1) - max(extent.x0, axes_box.x0)
        overlap_h = min(extent.y1, axes_box.y1) - max(extent.y0, axes_box.y0)
        assert overlap_w <= 1.0 or overlap_h <= 1.0, artist


def test_turning_the_toggle_off_restores_the_adaptive_layout(iec_canvas) -> None:
    adaptive = _canvas_box_inches(iec_canvas)
    iec_canvas.iec_scale_action.setChecked(True)
    assert _canvas_box_inches(iec_canvas) != pytest.approx(adaptive)

    iec_canvas.iec_scale_action.setChecked(False)

    assert _canvas_box_inches(iec_canvas) == pytest.approx(adaptive)
    if iec_canvas.secondary_axes is not None:
        assert iec_canvas.secondary_axes.get_position().bounds == pytest.approx(iec_canvas.axes.get_position().bounds)


# --- Main window ------------------------------------------------------------


def test_toggle_is_in_the_toolbar_of_the_three_db_versus_log_frequency_plots_only(main_window) -> None:
    iec_plots = {"spinorama", "on_axis_frequency_response", "max_spl"}
    for entry in main_window.plot_entries:
        title_bar = main_window.plot_docks[entry.plot_id].titleBarWidget()
        actions = [button.defaultAction() for button in title_bar.tool_buttons]
        texts = [action.text() for action in actions if action is not None]
        if entry.plot_id in iec_plots:
            assert entry.widget.iec_scale_action in actions, entry.plot_id
        else:
            assert "25 dB/dec" not in texts, entry.plot_id
    assert {entry.plot_id for entry in main_window.plot_entries} >= iec_plots
