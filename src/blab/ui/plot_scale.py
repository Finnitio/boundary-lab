"""IEC 60263 plot scale: the axes-box ratio for dB versus log-frequency plots."""

from __future__ import annotations

import math

IEC_DB_PER_DECADE = 25.0

Box = tuple[float, float, float, float]


def iec_axes_box(
    available: Box,
    x_limits: tuple[float, float],
    y_limits: tuple[float, float],
    *,
    db_per_decade: float = IEC_DB_PER_DECADE,
) -> Box:
    """Return the largest box centred in ``available`` that shows ``db_per_decade``.

    ``available`` is ``(x0, y0, width, height)`` in physical units (any length unit,
    the same on both axes). The returned box keeps height / width equal to
    (y span / ``db_per_decade``) / (x decades). When the limits do not define a
    ratio, the available box is returned unchanged.
    """

    x0, y0, width, height = (float(value) for value in available)
    x_low, x_high = sorted(float(value) for value in x_limits)
    y_span = abs(float(y_limits[1]) - float(y_limits[0]))
    if width <= 0.0 or height <= 0.0 or x_low <= 0.0 or db_per_decade <= 0.0:
        return x0, y0, width, height
    decades = math.log10(x_high / x_low)
    if not (math.isfinite(decades) and decades > 0.0 and math.isfinite(y_span) and y_span > 0.0):
        return x0, y0, width, height
    ratio = (y_span / db_per_decade) / decades
    box_width = min(width, height / ratio)
    box_height = box_width * ratio
    return (
        x0 + 0.5 * (width - box_width),
        y0 + 0.5 * (height - box_height),
        box_width,
        box_height,
    )
