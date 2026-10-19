"""Analysis catalog — the eight Infrared SDK analyses and their real parameters.

Every parameter here maps 1:1 onto a field of an Infrared SDK request payload
(see `dispatch.py`). Nothing is decorative: if a control moves, the simulation
changes. `frontend/src/catalog/analyses.ts` mirrors this file so the UI can
still render while the backend is down — keep the two in step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Control = Literal["slider", "select"]


@dataclass(frozen=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True)
class ParamDef:
    key: str
    label: str
    unit: str
    default: float | str
    control: Control = "slider"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: tuple[Option, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class KpiDef:
    key: str
    label: str
    unit: str


@dataclass(frozen=True)
class AnalysisDef:
    id: str
    label: str
    short: str
    description: str
    unit: str
    value_range: tuple[float, float]
    params: tuple[ParamDef, ...]
    kpis: tuple[KpiDef, ...]
    needs_weather: bool = False
    needs_time_period: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


# --- shared TimePeriod controls -------------------------------------------
#
# The server's sun-vector generator only honours a single month per run, so
# `start_month == end_month` is enforced by exposing one month control.
# `end_day` maxes at 28 by default so a window stays valid in every month;
# dispatch clamps it to the real month length anyway.

def _time_params(
    *,
    month: int,
    start_hour: int,
    end_hour: int,
    end_day: int = 28,
) -> tuple[ParamDef, ...]:
    return (
        ParamDef(
            key="month",
            label="Month",
            unit="",
            default=month,
            min=1,
            max=12,
            step=1,
            help="Single-month window — the inference layer generates sun vectors for one month per run.",
        ),
        ParamDef(key="start_day", label="First day", unit="", default=1, min=1, max=31, step=1),
        ParamDef(key="end_day", label="Last day", unit="", default=end_day, min=1, max=31, step=1),
        ParamDef(key="start_hour", label="First hour", unit="h", default=start_hour, min=0, max=23, step=1),
        ParamDef(key="end_hour", label="Last hour", unit="h", default=end_hour, min=0, max=23, step=1),
    )


CATALOG: tuple[AnalysisDef, ...] = (
    AnalysisDef(
        id="wind-speed",
        label="Wind speed at pedestrian level",
        short="Wind Speed",
        description="Steady-state wind magnitude near pedestrian height for one inflow condition.",
        unit="m/s",
        value_range=(0.0, 15.0),
        params=(
            ParamDef(
                key="wind_speed",
                label="Reference wind speed",
                unit="m/s",
                default=5.0,
                min=0.5,
                max=50,
                step=0.5,
                help=(
                    "Free-stream inflow speed, applied as a linear scalar on the inferred "
                    "wind-factor field. Fractional values are the normal case — a prevailing "
                    "speed from an EPW is a mean."
                ),
            ),
            ParamDef(
                key="wind_direction",
                label="Wind direction",
                unit="°",
                default=270,
                min=0,
                max=345,
                step=15,
                help="Meteorological convention — 270 means wind FROM the west.",
            ),
        ),
        kpis=(
            KpiDef("mean_speed", "Mean speed", "m/s"),
            KpiDef("max_speed", "Max speed", "m/s"),
            KpiDef("above_5_pct", "Area > 5 m/s", "%"),
        ),
        notes=("Single-direction snapshot. For a year of weather use Pedestrian Wind Comfort.",),
    ),
    AnalysisDef(
        id="pedestrian-wind-comfort",
        label="Pedestrian wind comfort",
        short="Ped. Comfort",
        description="Comfort class per cell over a weather window, using the selected standard.",
        unit="class",
        value_range=(0.0, 4.0),
        params=(
            ParamDef(
                key="criteria",
                label="Criterion",
                unit="",
                default="lawson-2001",
                control="select",
                options=(
                    Option("lawson-2001", "Lawson 2001"),
                    Option("lawson-1970", "Lawson 1970"),
                    Option("lawson-lddc", "Lawson LDDC"),
                    Option("vdi-3787", "VDI 3787"),
                    Option("davenport", "Davenport"),
                    Option("nen-8100-comfort", "NEN 8100 — comfort"),
                    Option("nen-8100-safety", "NEN 8100 — safety"),
                ),
                help="NEN 8100 safety scores storm risk, not comfort — a different question.",
            ),
            *_time_params(month=1, start_hour=8, end_hour=20),
        ),
        kpis=(
            KpiDef("comfortable_pct", "Comfortable area", "%"),
            KpiDef("worst_class", "Worst class", ""),
            KpiDef("mean_class", "Mean class", ""),
        ),
        needs_weather=True,
        needs_time_period=True,
    ),
    AnalysisDef(
        id="daylight-availability",
        label="Daylight availability",
        short="Daylight",
        description="Cumulative hours of usable daylight per cell over the window.",
        unit="h",
        value_range=(0.0, 300.0),
        params=_time_params(month=6, start_hour=9, end_hour=17),
        kpis=(
            KpiDef("mean_hours", "Mean daylight", "h"),
            KpiDef("max_hours", "Max daylight", "h"),
            KpiDef("dark_pct", "Area < 25% of max", "%"),
        ),
        needs_time_period=True,
    ),
    AnalysisDef(
        id="direct-sun-hours",
        label="Direct sun hours",
        short="Sun Hours",
        description="Cumulative un-occluded sun hours per cell, summed over the filtered hour set.",
        unit="h",
        value_range=(0.0, 300.0),
        params=_time_params(month=6, start_hour=9, end_hour=17),
        kpis=(
            KpiDef("mean_hours", "Mean sun hours", "h"),
            KpiDef("hours_per_day", "Mean per day", "h/d"),
            KpiDef("shaded_pct", "Area < 25% of max", "%"),
        ),
        needs_time_period=True,
        notes=("Absolute hours depend on window length — normalise before comparing runs.",),
    ),
    AnalysisDef(
        id="sky-view-factors",
        label="Sky view factors",
        short="Sky View",
        description="Share of the upper hemisphere visible from each ground cell.",
        unit="%",
        value_range=(0.0, 100.0),
        params=(),
        kpis=(
            KpiDef("mean_svf", "Mean SVF", "%"),
            KpiDef("min_svf", "Min SVF", "%"),
            KpiDef("open_pct", "Area > 50%", "%"),
        ),
        notes=("Pure geometry — no weather, no season. One run covers all conditions.",),
    ),
    AnalysisDef(
        id="solar-radiation",
        label="Solar radiation",
        short="Solar Rad.",
        description="Cumulative shortwave irradiance per cell over the weather window.",
        unit="kWh/m²",
        value_range=(0.0, 400.0),
        params=_time_params(month=6, start_hour=6, end_hour=20),
        kpis=(
            KpiDef("mean_irrad", "Mean irradiance", "kWh/m²"),
            KpiDef("max_irrad", "Max irradiance", "kWh/m²"),
            KpiDef("low_pct", "Area < 25% of max", "%"),
        ),
        needs_weather=True,
        needs_time_period=True,
    ),
    AnalysisDef(
        id="thermal-comfort-index",
        label="Thermal comfort index (UTCI)",
        short="UTCI",
        description="Universal Thermal Climate Index — outdoor felt temperature.",
        unit="°C",
        value_range=(-10.0, 50.0),
        params=_time_params(month=8, start_hour=10, end_hour=18),
        kpis=(
            KpiDef("mean_utci", "Mean UTCI", "°C"),
            KpiDef("max_utci", "Max UTCI", "°C"),
            KpiDef("no_stress_pct", "No thermal stress", "%"),
        ),
        needs_weather=True,
        needs_time_period=True,
        notes=("No thermal stress = 9-26 °C UTCI (ISB commission band).",),
    ),
    AnalysisDef(
        id="thermal-comfort-statistics",
        label="Thermal comfort statistics",
        short="Therm. Stats",
        description="Hours per cell falling in the selected comfort or stress band.",
        unit="h",
        value_range=(0.0, 300.0),
        params=(
            ParamDef(
                key="subtype",
                label="Band",
                unit="",
                default="heat-stress",
                control="select",
                options=(
                    Option("thermal-comfort", "Thermal comfort"),
                    Option("heat-stress", "Heat stress"),
                    Option("cold-stress", "Cold stress"),
                ),
                help="One band per run — each subtype is a separate simulation.",
            ),
            *_time_params(month=8, start_hour=8, end_hour=20),
        ),
        kpis=(
            KpiDef("mean_hours", "Mean hours in band", "h"),
            KpiDef("max_hours", "Max hours in band", "h"),
            KpiDef("exposed_pct", "Area > 50% of window", "%"),
        ),
        needs_weather=True,
        needs_time_period=True,
    ),
)

BY_ID: dict[str, AnalysisDef] = {a.id: a for a in CATALOG}


def get(analysis_id: str) -> AnalysisDef:
    try:
        return BY_ID[analysis_id]
    except KeyError:
        raise ValueError(
            f"Unknown analysis {analysis_id!r}. Known: {', '.join(BY_ID)}"
        ) from None


def coerce_params(analysis_id: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate + fill defaults for one analysis's parameters.

    Slider values are clamped to their declared range and snapped to `step`
    (an out-of-range slider is a UI bug, not a reason to fail a run); select
    values must be one of the declared options.
    """
    definition = get(analysis_id)
    raw = raw or {}
    out: dict[str, Any] = {}

    for p in definition.params:
        value = raw.get(p.key, p.default)
        if p.control == "select":
            allowed = {o.value for o in p.options}
            if value not in allowed:
                raise ValueError(
                    f"{analysis_id}.{p.key}: {value!r} is not one of {sorted(allowed)}"
                )
            out[p.key] = value
            continue

        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{analysis_id}.{p.key}: {value!r} is not a number") from None
        if p.min is not None:
            number = max(number, float(p.min))
        if p.max is not None:
            number = min(number, float(p.max))
        if p.step is not None and float(p.step).is_integer():
            number = float(round(number))
        out[p.key] = number

    unknown = set(raw) - set(out)
    if unknown:
        raise ValueError(
            f"{analysis_id}: unknown parameter(s) {sorted(unknown)}. "
            f"Accepted: {sorted(out)}"
        )
    return out


def to_json(definition: AnalysisDef) -> dict[str, Any]:
    payload = asdict(definition)
    payload["valueRange"] = list(definition.value_range)
    payload.pop("value_range")
    payload["needsWeather"] = payload.pop("needs_weather")
    payload["needsTimePeriod"] = payload.pop("needs_time_period")
    return payload


def catalog_json() -> list[dict[str, Any]]:
    return [to_json(a) for a in CATALOG]
