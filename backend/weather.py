"""EPW weather library — vetted library files plus per-project uploads.

The curated library lives in `weather_data/` and is described by
`weather_manifest.yaml` (see docs/weather-library.md). Files are parsed locally
and filtered with the same cascade the Infrared inference layer applies to a
`TimePeriod`, so the arrays we submit line up with the sun vectors it
generates for the same window.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml
from config import CUSTOM_WEATHER_DIR, PROJECT_ROOT, WEATHER_DIR, WEATHER_MANIFEST
from infrared_sdk.models import TimePeriod, WeatherDataPoint

# EPW data-line column indices (EnergyPlus Auxiliary Programs, table 2.8),
# mapped to the camelCase field names of infrared_sdk.models.WeatherDataPoint.
EPW_COLUMNS: dict[int, str] = {
    6: "dryBulbTemperature",
    7: "dewPointTemperature",
    8: "relativeHumidity",
    9: "atmosphericStationPressure",
    10: "extraterrestrialHorizontalRadiation",
    11: "extraterrestrialDirectNormalRadiation",
    12: "horizontalInfraredRadiationIntensity",
    13: "globalHorizontalRadiation",
    14: "directNormalRadiation",
    15: "diffuseHorizontalRadiation",
    16: "globalHorizontalIlluminance",
    17: "directNormalIlluminance",
    18: "diffuseHorizontalIlluminance",
    19: "znithLuminance",
    20: "windDirection",
    21: "windSpeed",
    22: "totalSkyCover",
    23: "opaqueSkyCover",
    24: "visibility",
    25: "ceilingHeight",
    28: "precipitableWater",
    29: "aerosolOpticalDepth",
    30: "snowDepth",
    31: "daysSinceLastSnowfall",
    32: "albedo",
    33: "liquidPrecipitationDepth",
    34: "liquidPrecipitationQuantity",
}

# EPW uses 9999/99999 style sentinels for missing values, per field. Anything
# at or above this magnitude in a radiation/illuminance column is missing data.
_MISSING_TOKENS = {"9999", "99999", "999999", "999.0", "9999.0", "99999.0"}


@dataclass(frozen=True)
class WeatherFile:
    id: str
    filename: str
    station_name: str
    station_id: str
    country: str
    latitude: float
    longitude: float
    elevation_m: float
    timezone_utc_offset: float
    data_type: str
    data_period: str
    path: Path
    source: str = "library"
    quality_score: str = ""
    recommended_for: str = ""
    limitations: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "station_name": self.station_name,
            "station_id": self.station_id,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "timezone_utc_offset": self.timezone_utc_offset,
            "data_type": self.data_type,
            "data_period": self.data_period,
            "source": self.source,
            "quality_score": self.quality_score,
            "recommended_for": self.recommended_for,
            "limitations": list(self.limitations),
        }


def _manifest_entries() -> list[dict[str, Any]]:
    if not WEATHER_MANIFEST.exists():
        return []
    data = yaml.safe_load(WEATHER_MANIFEST.read_text(encoding="utf-8")) or {}
    return list(data.get("files") or [])


def _from_manifest(entry: dict[str, Any]) -> WeatherFile | None:
    # `path` (relative to the repo root) lets an entry live outside weather_data/,
    # e.g. the generated examples/synthetic.epw.
    rel = entry.get("path")
    path = (PROJECT_ROOT / str(rel)) if rel else (WEATHER_DIR / str(entry.get("filename", "")))
    if not path.exists():
        return None
    return WeatherFile(
        id=str(entry["id"]),
        filename=path.name,
        station_name=str(entry.get("station_name", path.stem)),
        station_id=str(entry.get("station_id", "")),
        country=str(entry.get("country", "")),
        latitude=float(entry.get("latitude", 0.0)),
        longitude=float(entry.get("longitude", 0.0)),
        elevation_m=float(entry.get("elevation_m", 0.0)),
        timezone_utc_offset=float(entry.get("timezone_utc_offset", 0.0)),
        data_type=str(entry.get("data_type", "EPW")),
        data_period=str(entry.get("data_period", "")),
        path=path,
        quality_score=str(entry.get("quality_score", "")),
        recommended_for=str(entry.get("recommended_for") or ""),
        limitations=tuple(entry.get("limitations") or ()),
    )


def _header_metadata(path: Path) -> dict[str, Any]:
    """Read the EPW LOCATION line: city, state, country, source, WMO, lat, lon, tz, elevation."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        line = fh.readline()
    parts = [p.strip() for p in line.split(",")]
    if not parts or parts[0].upper() != "LOCATION":
        return {}

    def num(index: int) -> float:
        try:
            return float(parts[index])
        except (IndexError, ValueError):
            return 0.0

    return {
        "city": parts[1] if len(parts) > 1 else path.stem,
        "country": parts[3] if len(parts) > 3 else "",
        "station_id": parts[5] if len(parts) > 5 else "",
        "latitude": num(6),
        "longitude": num(7),
        "timezone_utc_offset": num(8),
        "elevation_m": num(9),
    }


def _from_epw_file(path: Path, *, file_id: str, source: str) -> WeatherFile:
    meta = _header_metadata(path)
    return WeatherFile(
        id=file_id,
        filename=path.name,
        station_name=str(meta.get("city") or path.stem),
        station_id=str(meta.get("station_id", "")),
        country=str(meta.get("country", "")),
        latitude=float(meta.get("latitude", 0.0)),
        longitude=float(meta.get("longitude", 0.0)),
        elevation_m=float(meta.get("elevation_m", 0.0)),
        timezone_utc_offset=float(meta.get("timezone_utc_offset", 0.0)),
        data_type="EPW",
        data_period="uploaded",
        path=path,
        source=source,
    )


def library(project_id: str | None = None) -> list[WeatherFile]:
    """Vetted library files, plus any EPW uploaded for this project."""
    files = [f for f in (_from_manifest(e) for e in _manifest_entries()) if f]

    # Library files present on disk but missing from the manifest are still
    # usable — they just carry no provenance, which the UI shows as such.
    known = {f.filename for f in files}
    for path in sorted(WEATHER_DIR.glob("*.epw")):
        if path.name not in known:
            files.append(_from_epw_file(path, file_id=f"file-{path.stem}", source="unvetted"))

    if project_id:
        for path in sorted((CUSTOM_WEATHER_DIR / project_id).glob("*.epw")):
            files.append(_from_epw_file(path, file_id=f"custom-{path.stem}", source="upload"))
    return files


def get(weather_id: str, project_id: str | None = None) -> WeatherFile:
    for f in library(project_id):
        if f.id == weather_id:
            return f
    raise ValueError(f"Unknown weather file {weather_id!r}")


def store_upload(project_id: str, filename: str, data: bytes) -> WeatherFile:
    target_dir = CUSTOM_WEATHER_DIR / project_id
    target_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(filename).name
    if not safe.lower().endswith(".epw"):
        safe += ".epw"
    target = target_dir / safe
    target.write_bytes(data)
    weather_file = _from_epw_file(target, file_id=f"custom-{target.stem}", source="upload")
    if not weather_file.latitude and not weather_file.longitude:
        target.unlink(missing_ok=True)
        raise ValueError("Not a readable EPW file — the LOCATION header line is missing.")
    return weather_file


def delete_project_weather(project_id: str) -> None:
    shutil.rmtree(CUSTOM_WEATHER_DIR / project_id, ignore_errors=True)


def _parse_value(token: str) -> float | None:
    token = token.strip()
    if not token or token in _MISSING_TOKENS:
        return None
    try:
        return float(token)
    except ValueError:
        return None


@lru_cache(maxsize=8)
def _read_rows(path_str: str, mtime: float) -> tuple[tuple[int, int, int, dict[str, float]], ...]:
    """Parse an EPW into (month, day, hour_of_day, fields) rows.

    `mtime` is part of the cache key so a re-uploaded file is re-read.
    """
    rows: list[tuple[int, int, int, dict[str, float]]] = []
    with Path(path_str).open("r", encoding="utf-8", errors="replace") as fh:
        for _ in range(8):  # 8 header lines before the hourly records
            fh.readline()
        for line in fh:
            parts = line.split(",")
            if len(parts) < 22:
                continue
            try:
                month = int(parts[1])
                day = int(parts[2])
                epw_hour = int(parts[3])
            except ValueError:
                continue
            # EPW hour 1..24 labels the hour ENDING at that clock time, so
            # hour 1 covers 00:00-01:00 -> hour-of-day 0.
            hour = (epw_hour - 1) % 24
            fields: dict[str, float] = {}
            for index, name in EPW_COLUMNS.items():
                if index < len(parts):
                    value = _parse_value(parts[index])
                    if value is not None:
                        fields[name] = value
            rows.append((month, day, hour, fields))
    return tuple(rows)


def read_rows(weather_file: WeatherFile) -> tuple[tuple[int, int, int, dict[str, float]], ...]:
    return _read_rows(str(weather_file.path), weather_file.path.stat().st_mtime)


def filter_weather_data(
    weather_file: WeatherFile, time_period: TimePeriod
) -> list[WeatherDataPoint]:
    """Apply the TimePeriod cascade (months -> days -> hours) to an EPW.

    Mirrors the server-side filter documented in the SDK reference: each level
    is an inclusive range, and the result is the cross-product of the three —
    not a continuous wall-clock span.
    """
    months = range(time_period.start_month, time_period.end_month + 1)
    days = range(time_period.start_day, time_period.end_day + 1)
    hours = range(time_period.start_hour, time_period.end_hour + 1)

    points: list[WeatherDataPoint] = []
    for month, day, hour, fields in read_rows(weather_file):
        if month in months and day in days and hour in hours:
            points.append(WeatherDataPoint(**fields))
    return points


def expected_row_count(time_period: TimePeriod, weather_file: WeatherFile) -> int:
    """How many hourly rows the cascade should yield — used to catch EPW gaps."""
    return len(filter_weather_data(weather_file, time_period))


def missing_fields(points: Iterable[WeatherDataPoint], required: Iterable[str]) -> list[str]:
    """Required camelCase fields that are absent or partial across the window.

    `extract_weather_fields` silently drops `None`s, which would submit arrays
    shorter than the sun-vector series and fail server-side with a length
    mismatch. Catching it here gives a message that names the EPW column.
    """
    points = list(points)
    total = len(points)
    gaps: list[str] = []
    for name in required:
        present = sum(1 for p in points if getattr(p, name, None) is not None)
        if present < total:
            gaps.append(f"{name} ({present}/{total} hours)")
    return gaps
