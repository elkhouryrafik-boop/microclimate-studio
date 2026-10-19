"""Generate the synthetic sample inputs (deterministic: re-running is byte-identical).

    python examples/make_sample.py [--out examples]

Writes:
  sample-site.ifc  three boxy buildings on a 160 x 120 m site (invented geometry)
  synthetic.epw    8,760-hour weather file from closed-form models (not measured data)
"""

from __future__ import annotations

import argparse
import math
import uuid
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.guid
import ifcopenshell.util.shape_builder

# Null Island (0.000, 0.000): a coordinate that belongs to no real place. UTC+0 keeps solar time consistent.
SITE_LAT = 0.0
SITE_LON = 0.0
SITE_ELEVATION_M = 5.0
TIMEZONE = 0.0

SITE_SIZE_M = (160.0, 120.0)
STOREY_HEIGHT_M = 3.2

# name, storeys, footprint polygon (site metres, counter-clockwise)
BUILDINGS = [
    ("Block A", 6, [(15, 60), (39, 60), (39, 84), (15, 84)]),
    ("Slab B", 3, [(60, 20), (100, 20), (100, 32), (60, 32)]),
    ("L-shape C", 9, [(105, 65), (123, 65), (123, 71), (111, 71), (111, 83), (105, 83)]),
]


def _dms(value: float) -> tuple[int, int, int, int]:
    sign = -1 if value < 0 else 1
    value = abs(value)
    deg = int(value)
    minutes = int((value - deg) * 60)
    seconds_f = ((value - deg) * 60 - minutes) * 60
    seconds = int(seconds_f)
    micro = int(round((seconds_f - seconds) * 1_000_000))
    return (sign * deg, sign * minutes, sign * seconds, sign * micro)


def build_ifc(path: Path) -> Path:
    model = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Synthetic sample site")
    ifcopenshell.api.unit.assign_unit(
        model, units=[ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT")]
    )
    ctx = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx
    )

    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Synthetic site")
    site.RefLatitude = _dms(SITE_LAT)
    site.RefLongitude = _dms(SITE_LON)
    site.RefElevation = SITE_ELEVATION_M
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)

    builder = ifcopenshell.util.shape_builder.ShapeBuilder(model)
    for name, n_storeys, footprint in BUILDINGS:
        building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name=name)
        ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
        for level in range(n_storeys):
            storey = ifcopenshell.api.root.create_entity(
                model, ifc_class="IfcBuildingStorey", name=f"{name} level {level + 1}"
            )
            ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
            wall = ifcopenshell.api.root.create_entity(
                model, ifc_class="IfcWall", name=f"{name} envelope level {level + 1}"
            )
            outline = builder.polyline([(float(x), float(y)) for x, y in footprint], closed=True)
            solid = builder.extrude(
                builder.profile(outline), magnitude=STOREY_HEIGHT_M, position=(0.0, 0.0, level * STOREY_HEIGHT_M)
            )
            rep = builder.get_representation(body, [solid])
            ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=rep)
            ifcopenshell.api.spatial.assign_container(model, products=[wall], relating_structure=storey)

    # Deterministic output: stable GlobalIds and a fixed header timestamp.
    namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "microclimate-studio.sample")
    for entity in model.by_type("IfcRoot"):
        entity.GlobalId = ifcopenshell.guid.compress(uuid.uuid5(namespace, str(entity.id())).hex)
    # Relationship members come back in hash order; sort them so the file is byte-stable.
    for rel in model.by_type("IfcRelAggregates"):
        rel.RelatedObjects = tuple(sorted(rel.RelatedObjects, key=lambda e: e.id()))
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        rel.RelatedElements = tuple(sorted(rel.RelatedElements, key=lambda e: e.id()))
    header = model.header.file_name
    header.time_stamp = "2026-01-01T00:00:00"
    header.author = ("synthetic",)
    header.organization = ("synthetic",)
    header.originating_system = "microclimate-studio make_sample.py"
    header.preprocessor_version = "n/a"

    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path


def _sin_altitude(doy: int, solar_hour: float) -> float:
    """Sine of the solar altitude at the site latitude."""
    decl = math.radians(23.45) * math.sin(2 * math.pi * (284 + doy) / 365)
    hour_angle = math.radians(15.0 * (solar_hour - 12.0))
    lat = math.radians(SITE_LAT)
    return math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)


def _row(month: int, day: int, hour: int, doy: int) -> str:
    """One EPW record; hour is the EPW hour 1..24 (hour ending)."""
    year_phase = 2 * math.pi * (doy - 110) / 365
    day_phase = 2 * math.pi * (hour - 9) / 24
    temp = 28.0 + 7.0 * math.sin(year_phase) + 5.0 * math.sin(day_phase)
    rh = min(95.0, max(15.0, 55.0 - 3.0 * (temp - 28.0)))
    gamma = math.log(rh / 100.0) + 17.62 * temp / (243.12 + temp)
    dew = 243.12 * gamma / (17.62 - gamma)

    solar_hour = hour - 0.5 + (SITE_LON - TIMEZONE * 15.0) / 15.0
    sin_alt = _sin_altitude(doy, solar_hour)
    if sin_alt > 0.02:
        dni = 900.0 * sin_alt**0.35
        dhi = 110.0 * sin_alt**0.5
        ghi = dni * sin_alt + dhi
    else:
        dni = dhi = ghi = 0.0
    etr = max(0.0, 1361.0 * sin_alt)
    wind_speed = max(0.2, 3.5 + 1.5 * math.sin(day_phase) + 0.8 * math.sin(2 * math.pi * doy / 365))
    wind_dir = (315.0 + 45.0 * math.sin(2 * math.pi * doy / 365 + day_phase)) % 360.0
    ir = 5.670374419e-8 * (temp + 273.15) ** 4 * 0.8

    fields = [
        2001, month, day, hour, 60, "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9?9?9?9*_*_*_*_*_*_*_",
        f"{temp:.1f}", f"{dew:.1f}", f"{rh:.0f}", "101325",
        f"{etr:.0f}", "1361", f"{ir:.0f}", f"{ghi:.0f}", f"{dni:.0f}", f"{dhi:.0f}",
        f"{ghi * 110:.0f}", f"{dni * 110:.0f}", f"{dhi * 110:.0f}", f"{dhi * 11:.0f}",
        f"{wind_dir:.0f}", f"{wind_speed:.1f}", "2", "2", "30.0", "77777",
        "9", "999999999", "20", "0.1000", "0", "88", "0.20", "0.0", "1",
    ]
    return ",".join(str(v) for v in fields)


def build_epw(path: Path) -> Path:
    lines = [
        f"LOCATION,Synthetic,-,-,SYN,000000,{SITE_LAT:.3f},{SITE_LON:.3f},{TIMEZONE:.1f},{SITE_ELEVATION_M:g}",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,Generated by examples/make_sample.py - not measured data",
        "COMMENTS 2,Closed-form sine/clear-sky models; for tests and the offline demo only",
        "DATA PERIODS,1,1,Data,Sunday, 1/ 1,12/31",
    ]
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    doy = 0
    for month, n_days in enumerate(days, start=1):
        for day in range(1, n_days + 1):
            doy += 1
            for hour in range(1, 25):
                lines.append(_row(month, day, hour, doy))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(build_ifc(args.out / "sample-site.ifc"))
    print(build_epw(args.out / "synthetic.epw"))


if __name__ == "__main__":
    main()
