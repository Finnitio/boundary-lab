"""Shared per-series visibility for plot canvases: Traces menu, legend clicks and greying."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from matplotlib.backend_bases import MouseButton
from PySide6.QtCore import QSignalBlocker

HIDDEN_LEGEND_ENTRY_ALPHA = 0.3
LEGEND_HANDLE_PICK_RADIUS = 5.0


class SeriesVisibilityMixin:
    """One visibility state per series, shared by the Traces menu and a clickable legend.

    Canvases keep ``_series_labels`` (displayed labels) and ``_series_visibility``
    (keyed by :meth:`_series_visibility_key`). A canvas with a Traces menu also has
    ``trace_filter_menu``/``trace_filter_action``. After a visibility change the
    mixin calls :meth:`_on_series_visibility_changed`, which re-applies line
    visibility and limits; canvases override :meth:`_apply_series_visibility` and
    :meth:`_update_visible_series_limits`.
    """

    def _series_visibility_key(self, label: str) -> str:
        """Key that stays the same when a series' displayed label changes."""
        return str(label)

    def is_series_visible(self, label: str) -> bool:
        """Return the series selection, including series not rendered yet."""
        return getattr(self, "_series_visibility", {}).get(self._series_visibility_key(label), True)

    def has_selected_traces(self) -> bool:
        labels = getattr(self, "_series_labels", ())
        return not labels or any(self.is_series_visible(label) for label in labels)

    def set_series_visible(self, label: str, visible: bool) -> None:
        key = self._series_visibility_key(label)
        if key not in {self._series_visibility_key(name) for name in getattr(self, "_series_labels", ())}:
            return
        visible = bool(visible)
        self._series_visibility[key] = visible
        for action_label, action in getattr(self, "_series_actions", {}).items():
            if self._series_visibility_key(action_label) == key and action.isChecked() != visible:
                with QSignalBlocker(action):
                    action.setChecked(visible)
        self.trace_visibility_changed.emit()
        self._on_series_visibility_changed()

    def _on_series_visibility_changed(self) -> None:
        self._apply_series_visibility()
        self._update_visible_series_limits()
        self._apply_manual_axis_limits()
        self._invalidate_crosshair_background()
        self.draw_idle()

    def _apply_series_visibility(self) -> None:
        raise NotImplementedError

    def _update_visible_series_limits(self) -> None:
        """Re-fit automatic limits to the visible series; fixed-range plots keep theirs."""

    def _sync_trace_filter_actions(self, labels: tuple[str, ...]) -> None:
        self.trace_filter_menu.clear()
        self._series_actions = {}
        for label in labels:
            action = self.trace_filter_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.is_series_visible(label))
            action.toggled.connect(lambda checked, series_label=label: self.set_series_visible(series_label, checked))
            self._series_actions[label] = action
        self.trace_filter_action.setEnabled(bool(labels))

    # Legend -------------------------------------------------------------

    def _show_series_legend(self, entries: Iterable[tuple[str, object]], **legend_kwargs) -> None:
        """Show every series line in the legend; hidden ones greyed, all clickable.

        ``entries`` pairs a series label with a line; several lines may share a
        label. The legend is rebuilt only when the entries change, so the layout
        stays put while series are toggled.
        """
        entries = tuple(entries)
        legend = self.axes.get_legend()
        current = getattr(self, "_series_legend", None)
        if legend is None or legend is not current or entries != getattr(self, "_series_legend_entries", ()):
            if legend is not None:
                legend.remove()
            self._build_series_legend(entries, legend_kwargs)
        self._style_series_legend()

    def _build_series_legend(self, entries: Sequence[tuple[str, object]], legend_kwargs: dict) -> None:
        self._series_legend_entries = entries
        self._series_legend_targets: dict[object, str] = {}
        self._series_legend = None
        if not entries:
            return
        legend_kwargs.setdefault("loc", "best")
        lines = [line for _label, line in entries]
        legend = self.axes.legend(lines, [line.get_label() for line in lines], **legend_kwargs)
        for (label, _line), handle, text in zip(entries, legend.legend_handles, legend.get_texts(), strict=True):
            handle.set_picker(LEGEND_HANDLE_PICK_RADIUS)
            text.set_picker(True)
            self._series_legend_targets[handle] = label
            self._series_legend_targets[text] = label
        self._series_legend = legend

    def _style_series_legend(self) -> None:
        for artist, label in getattr(self, "_series_legend_targets", {}).items():
            artist.set_alpha(None if self.is_series_visible(label) else HIDDEN_LEGEND_ENTRY_ALPHA)

    def _on_series_legend_pick(self, event) -> None:
        label = getattr(self, "_series_legend_targets", {}).get(event.artist)
        mouse_event = event.mouseevent
        if label is None or mouse_event.button != MouseButton.LEFT:
            return
        # The handle and the text of one entry can both report the same click.
        if mouse_event is getattr(self, "_last_series_legend_click", None):
            return
        self._last_series_legend_click = mouse_event
        self.set_series_visible(label, not self.is_series_visible(label))

    def _event_hits_series_legend(self, event) -> bool:
        legend = getattr(self, "_series_legend", None)
        x, y = getattr(event, "x", None), getattr(event, "y", None)
        if legend is None or x is None or y is None or legend is not self.axes.get_legend():
            return False
        return legend.get_window_extent().contains(x, y)


__all__ = ["HIDDEN_LEGEND_ENTRY_ALPHA", "SeriesVisibilityMixin"]
