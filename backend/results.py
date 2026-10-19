"""Turn a merged result grid into what the UI shows: KPIs, histogram, heatmap.

Grid conventions that matter here (SDK reference, grid-conventions.md):

* Cells outside the polygon are `NaN` — never zero. Treating them as zero
  drags every statistic toward nothing.
* Row 0 is the **south** edge, column 0 the west. Images are top-down, so the
  array is flipped once on the way to a PNG.
* Colour bounds come from `min_legend` / `max_legend`, not the data range —
  daylight and sun-hour distributions bunch near their maximum and look washed
  out otherwise.
"""

from __future__ import annotations

import io
import math
from typing import Any

import catalog
import numpy as np
from PIL import Image

HISTOGRAM_BINS = 20
MAX_CONTOUR_POINTS = 2500

# Shared jet ramp: blue -> cyan -> green -> yellow -> red. Mirrors
# `jetColor()` in the frontend catalog so the heatmap, the histogram bars and
# the legend all agree.
JET_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.00, (0, 0, 255)),
    (0.25, (0, 255, 255)),
    (0.50, (0, 255, 0)),
    (0.75, (255, 255, 0)),
    (1.00, (255, 0, 0)),
)

# UTCI "no thermal stress" band (ISB commission / Bröde et al. 2012).
UTCI_COMFORT_BAND = (9.0, 26.0)

# Pedestrian wind comfort: classes are ordered best-to-worst, so the two
# best classes are the ones people describe as sittable/standable.
PWC_COMFORTABLE_MAX_CLASS = 1


def jet_lut() -> np.ndarray:
    """256-entry RGB lookup table for the jet ramp."""
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255
        for (t0, c0), (t1, c1) in zip(JET_STOPS, JET_STOPS[1:]):
            if t <= t1 or t1 == 1.0:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                f = min(1.0, max(0.0, f))
                lut[i] = [round(c0[k] + (c1[k] - c0[k]) * f) for k in range(3)]
                break
    return lut


_LUT = jet_lut()


def legend_bounds(grid: np.ndarray, min_legend: float | None, max_legend: float | None) -> tuple[float, float]:
    valid = grid[np.isfinite(grid)]
    if valid.size == 0:
        return 0.0, 1.0
    lo = float(min_legend) if min_legend is not None else float(np.nanmin(valid))
    hi = float(max_legend) if max_legend is not None else float(np.nanmax(valid))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        lo, hi = float(np.nanmin(valid)), float(np.nanmax(valid))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def heatmap_png(grid: np.ndarray, lo: float, hi: float) -> bytes:
    """RGBA PNG of the grid, transparent outside the polygon, north up."""
    normalised = (grid - lo) / (hi - lo)
    normalised = np.clip(np.nan_to_num(normalised, nan=0.0), 0.0, 1.0)
    indices = (normalised * 255).astype(np.uint8)

    rgba = np.zeros((*grid.shape, 4), dtype=np.uint8)
    rgba[..., :3] = _LUT[indices]
    rgba[..., 3] = np.where(np.isfinite(grid), 255, 0)

    # Row 0 is the south edge; PNG row 0 is the top of the image.
    image = Image.fromarray(np.flipud(rgba), mode="RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def histogram(grid: np.ndarray, lo: float, hi: float) -> list[dict[str, float]]:
    valid = grid[np.isfinite(grid)]
    counts, edges = np.histogram(valid, bins=HISTOGRAM_BINS, range=(lo, hi))
    return [
        {
            "index": i,
            "min": round(float(edges[i]), 3),
            "max": round(float(edges[i + 1]), 3),
            "count": int(counts[i]),
        }
        for i in range(HISTOGRAM_BINS)
    ]


def contour_points(
    grid: np.ndarray, bounds: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    """Sparse lon/lat samples for the contour overlay.

    The overlay is the colour-blind cue required by the product's
    accessibility rule — value must be readable without relying on hue.
    """
    rows, cols = grid.shape
    if rows < 2 or cols < 2:
        return []
    west, south, east, north = bounds
    step = max(1, int(math.ceil(math.sqrt((rows * cols) / MAX_CONTOUR_POINTS))))

    points: list[dict[str, Any]] = []
    for row in range(0, rows, step):
        fy = row / (rows - 1)
        lat = south + fy * (north - south)
        for col in range(0, cols, step):
            value = grid[row, col]
            if not np.isfinite(value):
                continue
            fx = col / (cols - 1)
            points.append(
                {
                    "position": [west + fx * (east - west), lat],
                    "value": round(float(value), 3),
                }
            )
    return points


def _pct(mask: np.ndarray, valid_count: int) -> float:
    if valid_count == 0:
        return 0.0
    return round(float(mask.sum()) / valid_count * 100, 1)


def kpis(
    analysis_id: str,
    grid: np.ndarray,
    *,
    days_in_window: int,
    hours_in_window: int,
) -> list[dict[str, Any]]:
    definition = catalog.get(analysis_id)
    valid = grid[np.isfinite(grid)]
    count = int(valid.size)
    if count == 0:
        return [
            {"key": k.key, "label": k.label, "value": 0.0, "unit": k.unit}
            for k in definition.kpis
        ]

    mean = float(valid.mean())
    maximum = float(valid.max())
    minimum = float(valid.min())
    values: dict[str, float]

    if analysis_id == "wind-speed":
        values = {
            "mean_speed": round(mean, 2),
            "max_speed": round(maximum, 2),
            "above_5_pct": _pct(valid > 5.0, count),
        }
    elif analysis_id == "pedestrian-wind-comfort":
        values = {
            "comfortable_pct": _pct(valid <= PWC_COMFORTABLE_MAX_CLASS, count),
            "worst_class": round(maximum, 0),
            "mean_class": round(mean, 2),
        }
    elif analysis_id == "daylight-availability":
        values = {
            "mean_hours": round(mean, 1),
            "max_hours": round(maximum, 1),
            "dark_pct": _pct(valid < 0.25 * maximum, count),
        }
    elif analysis_id == "direct-sun-hours":
        values = {
            "mean_hours": round(mean, 1),
            "hours_per_day": round(mean / max(1, days_in_window), 2),
            "shaded_pct": _pct(valid < 0.25 * maximum, count),
        }
    elif analysis_id == "sky-view-factors":
        values = {
            "mean_svf": round(mean, 1),
            "min_svf": round(minimum, 1),
            "open_pct": _pct(valid > 50.0, count),
        }
    elif analysis_id == "solar-radiation":
        values = {
            "mean_irrad": round(mean, 1),
            "max_irrad": round(maximum, 1),
            "low_pct": _pct(valid < 0.25 * maximum, count),
        }
    elif analysis_id == "thermal-comfort-index":
        low, high = UTCI_COMFORT_BAND
        values = {
            "mean_utci": round(mean, 1),
            "max_utci": round(maximum, 1),
            "no_stress_pct": _pct((valid >= low) & (valid <= high), count),
        }
    elif analysis_id == "thermal-comfort-statistics":
        half = 0.5 * (hours_in_window or maximum or 1)
        values = {
            "mean_hours": round(mean, 1),
            "max_hours": round(maximum, 1),
            "exposed_pct": _pct(valid > half, count),
        }
    else:
        values = {}

    return [
        {
            "key": k.key,
            "label": k.label,
            "value": float(values.get(k.key, 0.0)),
            "unit": k.unit,
        }
        for k in definition.kpis
    ]
