"""Synthetic stand-in for the Infrared analysis engine (offline demo + tests).

NOT PHYSICS. Every field here is a cheap, deterministic closed-form function
of the site grid and the building heights, built so the fields *look*
plausible (shadows, wakes, sheltered corners) and react to the parameters.
Nothing is validated against measurements or against the real models; the
result carries ``engine == "fake"`` and the UI shows a "synthetic" badge.

Inputs are the same objects the real path gets (site polygon in lon/lat,
DotBim meshes in site metres, an optional EPW). The output is the same
``RunOutcome`` shape, so ``results.py`` runs unchanged.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polygon as polygon_lib
import weather as weather_lib

MAX_CELLS_PER_SIDE = 256
MIN_CELL_M = 2.0
SVF_AZIMUTHS = 16
HORIZON_RANGE_M = 120.0


# --- grid + height field --------------------------------------------------


def _grid_axes(polygon: dict) -> tuple[tuple[float, float, float, float], float, int, int]:
    west, south, east, north = polygon_lib.polygon_bounds(polygon)
    anchor = polygon_lib.GeoAnchor(latitude=south, longitude=west)
    width, height = anchor.to_meters(east, north)
    cell = max(MIN_CELL_M, max(width, height) / MAX_CELLS_PER_SIDE)
    cols = max(2, int(math.ceil(width / cell)))
    rows = max(2, int(math.ceil(height / cell)))
    return (west, south, east, north), cell, rows, cols


def _mesh_arrays(mesh: Any) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(mesh, dict):
        coords, idx = mesh["coordinates"], mesh["indices"]
    else:
        coords, idx = mesh.coordinates, mesh.indices
    return (
        np.asarray(coords, dtype=float).reshape(-1, 3),
        np.asarray(idx, dtype=int).reshape(-1, 3),
    )


def height_field(meshes: dict[str, Any], rows: int, cols: int, cell: float) -> np.ndarray:
    """Building height (m) per cell, 0 on open ground. Row 0 is the south edge.

    Rasterises every non-vertical triangle (roofs and floors) and keeps the
    tallest vertex under each cell centre.
    """
    height = np.zeros((rows, cols))
    for mesh in meshes.values():
        coords, idx = _mesh_arrays(mesh)
        for tri in coords[idx]:
            (x0, y0, _), (x1, y1, _), (x2, y2, _) = tri
            det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(det) < 1e-9:  # vertical wall: no footprint of its own
                continue
            j0 = max(0, int(math.floor(min(x0, x1, x2) / cell - 0.5)))
            j1 = min(cols - 1, int(math.ceil(max(x0, x1, x2) / cell - 0.5)))
            i0 = max(0, int(math.floor(min(y0, y1, y2) / cell - 0.5)))
            i1 = min(rows - 1, int(math.ceil(max(y0, y1, y2) / cell - 0.5)))
            if j1 < j0 or i1 < i0:
                continue
            xs = (np.arange(j0, j1 + 1) + 0.5) * cell
            ys = (np.arange(i0, i1 + 1) + 0.5) * cell
            px, py = np.meshgrid(xs, ys)
            a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / det
            b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / det
            c = 1.0 - a - b
            inside = (a >= -1e-9) & (b >= -1e-9) & (c >= -1e-9)
            block = height[i0 : i1 + 1, j0 : j1 + 1]
            np.maximum(block, np.where(inside, float(tri[:, 2].max()), 0.0), out=block)
    return height


# --- geometry helpers -----------------------------------------------------


def _shifted(field: np.ndarray, di: np.ndarray, dj: np.ndarray, fill: float) -> np.ndarray:
    """field sampled at (i+di, j+dj); out-of-grid samples return `fill`."""
    rows, cols = field.shape
    ii = np.arange(rows)[:, None] + di
    jj = np.arange(cols)[None, :] + dj
    ok = (ii >= 0) & (ii < rows) & (jj >= 0) & (jj < cols)
    out = field[np.clip(ii, 0, rows - 1), np.clip(jj, 0, cols - 1)]
    return np.where(ok, out, fill)


def _max_obstruction_tan(height: np.ndarray, cell: float, bearing_deg: float) -> np.ndarray:
    """Tangent of the highest obstruction angle looking toward `bearing_deg`.

    Bearing is degrees clockwise from north. Ground cells see the roof tops of
    the buildings along the ray; a cell inside a building is handled by the
    caller (masked out).
    """
    rad = math.radians(bearing_deg)
    ei, ej = math.cos(rad), math.sin(rad)  # north = +row, east = +col
    best = np.zeros_like(height)
    steps = int(HORIZON_RANGE_M / cell)
    for k in range(1, steps + 1):
        dist = k * cell
        di = int(round(ei * k))
        dj = int(round(ej * k))
        seen = _shifted(height, np.array(di), np.array(dj), 0.0)
        np.maximum(best, seen / dist, out=best)
    return best


def sun_position(latitude: float, day_of_year: int, hour: float) -> tuple[float, float]:
    """(elevation_deg, azimuth_deg_from_north) from the textbook declination formula."""
    decl = math.radians(23.44) * math.sin(2 * math.pi * (284 + day_of_year) / 365)
    lat = math.radians(latitude)
    hour_angle = math.radians(15.0 * (hour - 12.0))
    sin_el = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    el = math.asin(max(-1.0, min(1.0, sin_el)))
    cos_el = max(1e-9, math.cos(el))
    cos_az = (math.sin(decl) - math.sin(el) * math.sin(lat)) / (cos_el * max(1e-9, math.cos(lat)))
    az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    if hour_angle > 0:
        az = 360.0 - az
    return math.degrees(el), az


def sky_view_factor(height: np.ndarray, cell: float) -> np.ndarray:
    """0..1 per cell: mean of cos^2(horizon elevation) over 16 azimuths."""
    acc = np.zeros_like(height)
    for k in range(SVF_AZIMUTHS):
        tan_el = _max_obstruction_tan(height, cell, k * 360.0 / SVF_AZIMUTHS)
        acc += 1.0 / (1.0 + tan_el**2)  # cos^2(atan(t))
    return acc / SVF_AZIMUTHS


def _lit_mask(height: np.ndarray, cell: float, elevation: float, azimuth: float) -> np.ndarray:
    if elevation <= 0.5:
        return np.zeros(height.shape, dtype=bool)
    tan_obstruction = _max_obstruction_tan(height, cell, azimuth)
    return tan_obstruction < math.tan(math.radians(elevation))


# --- window + weather -----------------------------------------------------


def _window(params: dict[str, Any]) -> tuple[int, list[int], int]:
    """(month, hours in window, number of days) from clamped params."""
    import dispatch  # local: dispatch imports this module lazily

    period = dispatch.time_period(params)
    hours = list(range(period.start_hour, period.end_hour + 1))
    days = period.end_day - period.start_day + 1
    return period.start_month, hours, days


def _day_of_year(month: int, day: int) -> int:
    return int(sum(_DAYS[: month - 1]) + day)


_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _weather_means(weather_file: Any, params: dict[str, Any]) -> dict[str, float]:
    import dispatch

    period = dispatch.time_period(params)
    points = weather_lib.filter_weather_data(weather_file, period)

    def mean(name: str, default: float) -> float:
        values = [getattr(p, name, None) for p in points]
        values = [v for v in values if v is not None]
        return float(np.mean(values)) if values else default

    return {
        "temp": mean("dryBulbTemperature", 25.0),
        "rh": mean("relativeHumidity", 50.0),
        "wind": mean("windSpeed", 3.0),
        "wind_dir": mean("windDirection", 270.0),
        "ghi": mean("globalHorizontalRadiation", 400.0),
        "dni": mean("directNormalRadiation", 500.0),
        "dhi": mean("diffuseHorizontalRadiation", 150.0),
        "hours": float(len(points)),
    }


# --- fields ---------------------------------------------------------------


def _wake_wind(
    height: np.ndarray, cell: float, base_speed: float, from_bearing: float
) -> np.ndarray:
    """Wind speed with a simple lee deficit and corner acceleration.

    Wind blows FROM `from_bearing`; a cell is in the lee of a building if the
    upwind ray hits a roof, with the deficit fading over ~8 building heights.
    """
    tan_up = _max_obstruction_tan(height, cell, from_bearing)
    shelter = np.clip(tan_up / 0.6, 0.0, 1.0)  # ~31 deg obstruction = fully sheltered
    speed = base_speed * (1.0 - 0.75 * shelter)
    # Flanking acceleration: cells just beside tall blocks (side rays see a block).
    side = np.maximum(
        _max_obstruction_tan(height, cell, from_bearing + 90.0),
        _max_obstruction_tan(height, cell, from_bearing - 90.0),
    )
    boost = np.clip(side / 0.8, 0.0, 1.0) * (1.0 - shelter)
    return speed * (1.0 + 0.35 * boost)


def _compute(
    analysis_id: str,
    params: dict[str, Any],
    height: np.ndarray,
    cell: float,
    latitude: float,
    weather_file: Any,
) -> tuple[np.ndarray, float, float]:
    """Return (grid, min_legend, max_legend) with NaN on building footprints."""
    shape = height.shape

    if analysis_id == "wind-speed":
        grid = _wake_wind(height, cell, float(params["wind_speed"]), float(params["wind_direction"]))
        return grid, 0.0, max(1.0, float(params["wind_speed"]) * 1.6)

    if analysis_id == "sky-view-factors":
        return sky_view_factor(height, cell) * 100.0, 0.0, 100.0

    if analysis_id == "pedestrian-wind-comfort":
        met = _weather_means(weather_file, params)
        # Eight wind sectors from the window's mean speed; class = worst sector.
        worst = np.zeros(shape)
        for sector in range(8):
            speed = _wake_wind(height, cell, met["wind"] * 1.0, sector * 45.0)
            weight = 1.0 if sector == round(met["wind_dir"] / 45.0) % 8 else 0.55
            worst = np.maximum(worst, speed * weight)
        # Lawson-like thresholds (m/s) -> class 0 (sitting) .. 4 (uncomfortable).
        grid = np.digitize(worst, [1.8, 3.6, 5.3, 7.6]).astype(float)
        return grid, 0.0, 4.0

    month, hours, days = _window(params)
    mid_day = _day_of_year(month, max(1, min(28, (int(params["start_day"]) + int(params["end_day"])) // 2)))
    sample_hours = hours if len(hours) <= 24 else hours[:24]

    lit_hours = np.zeros(shape)
    daylight_hours = 0.0
    for h in sample_hours:
        el, az = sun_position(latitude, mid_day, h + 0.5)
        if el > 0.5:
            daylight_hours += 1.0
        lit_hours += _lit_mask(height, cell, el, az)
    lit_hours *= days
    daylight_hours *= days

    if analysis_id == "direct-sun-hours":
        return lit_hours, 0.0, max(1.0, daylight_hours)

    svf = sky_view_factor(height, cell)

    if analysis_id == "daylight-availability":
        grid = daylight_hours * (0.2 + 0.8 * svf**2) * 0.4 + lit_hours * 0.6
        return grid, 0.0, max(1.0, daylight_hours)

    met = _weather_means(weather_file, params)

    if analysis_id == "solar-radiation":
        n = max(1, len(sample_hours)) * days
        kwh_direct = met["dni"] * (lit_hours / max(1, n)) * 0.55 * n / 1000.0
        kwh_diffuse = met["dhi"] * svf * n / 1000.0
        grid = kwh_direct + kwh_diffuse
        return grid, 0.0, max(1.0, float(np.nanmax(grid)))

    # UTCI-like and band-hours fields share one synthetic apparent temperature.
    sun_fraction = lit_hours / max(1.0, len(sample_hours) * days)
    wind = _wake_wind(height, cell, max(0.5, met["wind"]), met["wind_dir"])
    utci = (
        met["temp"]
        + 7.0 * sun_fraction * min(1.0, met["dni"] / 700.0 + 0.3)
        - 1.3 * (wind - 2.0)
        - 1.5 * (1.0 - svf)
        + 0.03 * (met["rh"] - 50.0)
    )

    if analysis_id == "thermal-comfort-index":
        return utci, -10.0, 50.0

    if analysis_id == "thermal-comfort-statistics":
        window_hours = max(1.0, met["hours"])
        subtype = params["subtype"]
        if subtype == "heat-stress":
            frac = 1.0 / (1.0 + np.exp(-(utci - 41.0) / 1.5))
        elif subtype == "cold-stress":
            frac = 1.0 / (1.0 + np.exp((utci - 9.0) / 2.5))
        else:  # thermal-comfort band 9..26
            frac = np.exp(-(((utci - 17.5) / 8.5) ** 4))
        return frac * window_hours, 0.0, window_hours

    raise ValueError(f"No fake rule for {analysis_id!r}")


def run(
    analysis_id: str,
    params: dict[str, Any],
    *,
    polygon: dict,
    meshes: dict[str, Any],
    latitude: float,
    longitude: float,
    weather_file: Any,
    hours_in_window: int,
):
    """Same contract as the SDK path in `dispatch.run`, minus the network."""
    from dispatch import RunOutcome

    bounds, cell, rows, cols = _grid_axes(polygon)
    height = height_field(meshes, rows, cols, cell)
    grid, lo, hi = _compute(analysis_id, params, height, cell, latitude, weather_file)

    grid = np.asarray(grid, dtype=float).copy()
    grid[height > 0.0] = np.nan  # pedestrian-level analyses: no value inside buildings

    return RunOutcome(
        grid=grid,
        bounds=bounds,
        min_legend=lo,
        max_legend=hi,
        succeeded_jobs=1,
        total_jobs=1,
        failed_jobs=[],
        hours_in_window=hours_in_window,
        criteria=params.get("criteria"),
        subtype=params.get("subtype"),
        engine="fake",
    )
