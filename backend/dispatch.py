"""Turn catalog parameters into Infrared SDK payloads and run them.

Everything that knows about SDK request classes lives here. The invariants
that bite (integer wind speed, single-month windows, weather arrays that must
match the sun-vector series 1:1) are enforced before submission, so a mistake
surfaces as a sentence rather than a 30-second round trip to a validation
error.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import Any

import catalog
import config
import weather as weather_lib
from infrared_sdk import InfraredClient
from infrared_sdk.analyses.types import (
    AnalysesName,
    BaseAnalysisPayload,
    PwcCriteria,
    PwcModelRequest,
    SolarModelRequest,
    SolarRadiationModelRequest,
    SvfModelRequest,
    TcsModelBaseRequest,
    TcsModelRequest,
    TcsSubtype,
    UtciModelBaseRequest,
    UtciModelRequest,
    WindModelRequest,
)
from infrared_sdk.buildings.types import DotBimMesh
from infrared_sdk.models import Location, TimePeriod, extract_weather_fields
from weather import WeatherFile

# Weather columns each analysis needs present for every hour of the window.
REQUIRED_WEATHER_FIELDS: dict[str, tuple[str, ...]] = {
    "pedestrian-wind-comfort": ("windSpeed", "windDirection"),
    "solar-radiation": ("diffuseHorizontalRadiation", "directNormalRadiation"),
    "thermal-comfort-index": (
        "horizontalInfraredRadiationIntensity",
        "diffuseHorizontalRadiation",
        "directNormalRadiation",
        "globalHorizontalRadiation",
        "dryBulbTemperature",
        "windSpeed",
        "relativeHumidity",
    ),
}
REQUIRED_WEATHER_FIELDS["thermal-comfort-statistics"] = REQUIRED_WEATHER_FIELDS[
    "thermal-comfort-index"
]


@dataclass
class RunOutcome:
    grid: Any  # numpy 2D array, NaN outside the polygon
    bounds: tuple[float, float, float, float] | None
    min_legend: float | None
    max_legend: float | None
    succeeded_jobs: int
    total_jobs: int
    failed_jobs: list[str]
    hours_in_window: int
    criteria: str | None = None
    subtype: str | None = None
    engine: str = "infrared"


def time_period(params: dict[str, Any]) -> TimePeriod:
    """Build a single-month TimePeriod, clamped to the month's real length."""
    month = int(params["month"])
    days_in_month = calendar.monthrange(2024, month)[1]  # leap year: allows 29 Feb
    start_day = min(int(params["start_day"]), days_in_month)
    end_day = min(int(params["end_day"]), days_in_month)
    if end_day < start_day:
        start_day, end_day = end_day, start_day

    start_hour = int(params["start_hour"])
    end_hour = int(params["end_hour"])
    if end_hour < start_hour:
        start_hour, end_hour = end_hour, start_hour
    if start_day == end_day and start_hour == end_hour:
        raise ValueError(
            "The time window is zero-length — widen the hour range or the day range."
        )

    return TimePeriod(
        start_month=month,
        start_day=start_day,
        start_hour=start_hour,
        end_month=month,
        end_day=end_day,
        end_hour=end_hour,
    )


def _weather_points(
    analysis_id: str, weather_file: WeatherFile | None, period: TimePeriod
) -> list:
    if weather_file is None:
        raise ValueError(
            f"{catalog.get(analysis_id).label} needs a weather file — pick one from the library."
        )
    points = weather_lib.filter_weather_data(weather_file, period)
    if not points:
        raise ValueError(
            f"{weather_file.filename} has no hours inside the selected window "
            f"(month {period.start_month}, days {period.start_day}-{period.end_day}, "
            f"hours {period.start_hour}-{period.end_hour})."
        )

    gaps = weather_lib.missing_fields(points, REQUIRED_WEATHER_FIELDS[analysis_id])
    if gaps:
        # extract_weather_fields drops None silently, which would submit arrays
        # shorter than the sun-vector series and fail deep in inference.
        raise ValueError(
            f"{weather_file.filename} has gaps in the columns this analysis needs: "
            + ", ".join(gaps)
            + ". Pick another station or a different window."
        )
    return points


def build_payload(
    analysis_id: str,
    params: dict[str, Any],
    *,
    latitude: float,
    longitude: float,
    weather_file: WeatherFile | None,
) -> tuple[Any, int]:
    """Return `(payload, hours_in_window)` for one run."""
    definition = catalog.get(analysis_id)
    location = Location(latitude=latitude, longitude=longitude)
    period = time_period(params) if definition.needs_time_period else None
    points = (
        _weather_points(analysis_id, weather_file, period)
        if definition.needs_weather and period is not None
        else []
    )
    hours = len(points)

    if analysis_id == "wind-speed":
        return (
            WindModelRequest(
                analysis_type=AnalysesName.wind_speed,
                # Speed is continuous — the model applies it as a linear scalar,
                # so rounding 3.9 to 4 moves every cell. Direction must be a
                # whole bearing; the SDK rejects fractions outright.
                wind_speed=float(params["wind_speed"]),
                wind_direction=int(params["wind_direction"]),
            ),
            0,
        )

    if analysis_id == "sky-view-factors":
        return SvfModelRequest(analysis_type=AnalysesName.sky_view_factors), 0

    if analysis_id in ("daylight-availability", "direct-sun-hours"):
        name = (
            AnalysesName.daylight_availability
            if analysis_id == "daylight-availability"
            else AnalysesName.direct_sun_hours
        )
        return (
            SolarModelRequest(
                analysis_type=name,
                latitude=latitude,
                longitude=longitude,
                time_period=period,
            ),
            0,
        )

    if analysis_id == "pedestrian-wind-comfort":
        fields = extract_weather_fields(points, ["windSpeed", "windDirection"])
        return (
            PwcModelRequest(
                analysis_type=AnalysesName.pedestrian_wind_comfort,
                criteria=PwcCriteria(params["criteria"]),
                latitude=latitude,
                longitude=longitude,
                **fields,
            ),
            hours,
        )

    if analysis_id == "solar-radiation":
        return (
            SolarRadiationModelRequest.from_weatherfile_payload(
                payload=BaseAnalysisPayload(analysis_type=AnalysesName.solar_radiation),
                location=location,
                time_period=period,
                weather_data=points,
            ),
            hours,
        )

    if analysis_id == "thermal-comfort-index":
        return (
            UtciModelRequest.from_weatherfile_payload(
                payload=UtciModelBaseRequest(analysis_type=AnalysesName.thermal_comfort_index),
                location=location,
                time_period=period,
                weather_data=points,
            ),
            hours,
        )

    if analysis_id == "thermal-comfort-statistics":
        return (
            TcsModelRequest.from_weatherfile_payload(
                payload=TcsModelBaseRequest(
                    analysis_type=AnalysesName.thermal_comfort_statistics,
                    subtype=TcsSubtype(params["subtype"]),
                ),
                location=location,
                time_period=period,
                weather_data=points,
            ),
            hours,
        )

    raise ValueError(f"No dispatch rule for {analysis_id!r}")


def to_meshes(geometry: dict[str, Any]) -> dict[str, DotBimMesh]:
    return {
        key: DotBimMesh(
            mesh_id=mesh["mesh_id"],
            coordinates=mesh["coordinates"],
            indices=mesh["indices"],
        )
        for key, mesh in geometry["meshes"].items()
    }


def run(
    analysis_id: str,
    params: dict[str, Any],
    *,
    polygon: dict,
    meshes: dict[str, DotBimMesh],
    latitude: float,
    longitude: float,
    weather_file: WeatherFile | None,
    job_timeout: int = 300,
    area_timeout: int = 1800,
) -> RunOutcome:
    payload, hours = build_payload(
        analysis_id,
        params,
        latitude=latitude,
        longitude=longitude,
        weather_file=weather_file,
    )

    if config.engine() == "fake":
        # Validation above is shared; only the network call is replaced.
        import fake_engine

        return fake_engine.run(
            analysis_id,
            params,
            polygon=polygon,
            meshes=meshes,
            latitude=latitude,
            longitude=longitude,
            weather_file=weather_file,
            hours_in_window=hours,
        )

    with InfraredClient() as client:
        result = client.run_area_and_wait(
            payload,
            polygon,
            buildings=meshes,
            job_timeout=job_timeout,
            area_timeout=area_timeout,
        )

    return RunOutcome(
        grid=result.merged_grid,
        bounds=getattr(result, "bounds", None),
        min_legend=getattr(result, "min_legend", None),
        max_legend=getattr(result, "max_legend", None),
        succeeded_jobs=getattr(result, "succeeded_jobs", 0),
        total_jobs=getattr(result, "total_jobs", 0),
        failed_jobs=list(getattr(result, "failed_jobs", []) or []),
        hours_in_window=hours,
        criteria=params.get("criteria"),
        subtype=params.get("subtype"),
    )
