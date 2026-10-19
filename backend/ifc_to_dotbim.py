"""IFC (Revit export) -> DotBim meshes + site polygon + scene footprints.

Revit writes IFC natively (File -> Export -> IFC), so this is the one import
path the office already produces. IfcOpenShell triangulates headlessly — no
Revit licence, any OS.

What comes out:

* `meshes` — one DotBim-shaped mesh per `IfcBuilding`, in site metres with the
  site polygon's bbox SW corner as origin. This is what the SDK consumes.
* `footprints` — extruded outlines per storey in `[lon, lat]`, for the DeckGL
  scene. Cheap to render and honest about the massing (a podium reads as a
  podium), where a single convex hull per building would flatten it to a box.
* `polygon` — the auto-derived site polygon (building extent + buffer).
"""

from __future__ import annotations

import math
import multiprocessing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.geolocation
from config import MAX_SITE_SPAN_M, MAX_TRIANGLES_PER_BUILDING, SITE_BUFFER_M
from polygon import GeoAnchor, polygon_span_m, site_polygon
from shapely.geometry import MultiPoint, MultiPolygon, Polygon
from shapely.ops import unary_union

# Element classes that make up the exterior mass. Microclimate models care
# about the shape air and sun meet, so MEP, furniture, spaces and annotations
# are left out — they only inflate the payload.
MASS_CLASSES: tuple[str, ...] = (
    "IfcWall",
    "IfcSlab",
    "IfcRoof",
    "IfcCurtainWall",
    "IfcPlate",
    "IfcMember",
    "IfcColumn",
    "IfcBeam",
    "IfcStair",
    "IfcRamp",
    "IfcCovering",
    "IfcShadingDevice",
    "IfcBuildingElementProxy",
)

# Footprint pieces smaller than this are export noise (a stray sweep, a
# detached fixing) and clutter the scene without describing the massing.
MIN_FOOTPRINT_AREA_M2 = 4.0


@dataclass
class ScenePart:
    """One extruded outline for the 3D scene."""

    polygon: list[list[float]]  # [[lon, lat], ...]
    height: float

    def to_json(self) -> dict[str, Any]:
        return {"polygon": self.polygon, "height": round(self.height, 2)}


@dataclass
class ParsedModel:
    meshes: dict[str, dict[str, Any]]
    footprints: list[ScenePart]
    polygon: dict
    georeferenced: bool
    stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Accumulator:
    """Per-building vertex/face accumulation in the working metre frame."""

    coordinates: list[float] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    vertex_count: int = 0
    # (storey label -> list of shapely polygons) for the scene footprints
    storey_shapes: dict[str, list[Polygon]] = field(default_factory=dict)

    def add(self, verts: list[float], faces: list[int]) -> None:
        offset = self.vertex_count
        self.coordinates.extend(verts)
        self.indices.extend(index + offset for index in faces)
        self.vertex_count += len(verts) // 3


def _dms_to_dd(value: Iterable[int] | None) -> float | None:
    """IfcSite stores lat/lon as (degrees, minutes, seconds[, millionth-seconds])."""
    if not value:
        return None
    parts = list(value)
    if len(parts) < 3:
        return None
    return ifcopenshell.util.geolocation.dms2dd(*parts[:4])


def _site_reference(model: ifcopenshell.file) -> tuple[float, float] | None:
    for site in model.by_type("IfcSite"):
        lat = _dms_to_dd(getattr(site, "RefLatitude", None))
        lon = _dms_to_dd(getattr(site, "RefLongitude", None))
        if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0):
            return lat, lon
    return None


def _container_labels(element: ifcopenshell.entity_instance) -> tuple[str, str]:
    """`(building key, storey label)` for one element, with sane fallbacks."""
    building = ifcopenshell.util.element.get_container(element, ifc_class="IfcBuilding")
    storey = ifcopenshell.util.element.get_container(element, ifc_class="IfcBuildingStorey")

    building_key = "building"
    if building is not None:
        building_key = getattr(building, "GlobalId", None) or getattr(building, "Name", None) or "building"
    storey_label = "level"
    if storey is not None:
        storey_label = getattr(storey, "Name", None) or getattr(storey, "GlobalId", None) or "level"
    return str(building_key), str(storey_label)


def _rotation(theta_deg: float) -> tuple[float, float]:
    """cos/sin for rotating project coordinates into a north-up frame.

    `get_true_north` answers "how do I rotate project north to get true
    north?" (anticlockwise positive), so the inverse rotation puts true north
    on +Y — which is the frame the SDK expects.
    """
    theta = math.radians(-theta_deg)
    return math.cos(theta), math.sin(theta)


def _element_footprint(xy: list[tuple[float, float]]) -> Polygon | None:
    """Convex hull of one element's plan projection.

    Per element a hull is faithful — walls, slabs and columns are convex in
    plan. The union across a storey is what recovers L-shapes and courtyards,
    so nothing is lost by not hulling at building level.
    """
    if len(xy) < 3:
        return None
    xs = {round(x, 3) for x, _ in xy}
    ys = {round(y, 3) for _, y in xy}
    if len(xs) < 2 or len(ys) < 2:  # vertical sliver — no plan extent
        return None
    hull = MultiPoint(xy).convex_hull
    if not isinstance(hull, Polygon) or hull.is_empty or hull.area < 0.25:
        return None
    return hull


def parse(
    ifc_path: Path,
    *,
    fallback_latitude: float,
    fallback_longitude: float,
    buffer_m: float = SITE_BUFFER_M,
) -> ParsedModel:
    model = ifcopenshell.open(str(ifc_path))
    warnings: list[str] = []

    elements = [e for cls in MASS_CLASSES for e in model.by_type(cls)]
    if not elements:
        raise ValueError(
            "No building geometry found. Export from Revit with File -> Export -> IFC "
            "and keep walls, slabs and roofs in the export scope."
        )

    cos_t, sin_t = _rotation(ifcopenshell.util.geolocation.get_true_north(model))

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)  # bake placements; geometry comes back in metres

    accumulators: dict[str, _Accumulator] = {}
    storey_tops: dict[tuple[str, str], float] = {}
    min_x = min_y = min_z = math.inf
    max_x = max_y = max_z = -math.inf
    triangles = 0

    iterator = ifcopenshell.geom.iterator(
        settings, model, max(1, multiprocessing.cpu_count() - 1), include=elements
    )
    if iterator.initialize():
        while True:
            shape = iterator.get()
            raw_verts = shape.geometry.verts
            faces = list(shape.geometry.faces)
            if not raw_verts or not faces:
                if not iterator.next():
                    break
                continue

            element = model.by_id(shape.id)
            building_key, storey_label = _container_labels(element)
            accumulator = accumulators.setdefault(building_key, _Accumulator())

            rotated: list[float] = []
            xy: list[tuple[float, float]] = []
            top = -math.inf
            for i in range(0, len(raw_verts), 3):
                px, py, pz = raw_verts[i], raw_verts[i + 1], raw_verts[i + 2]
                x = px * cos_t + py * sin_t
                y = -px * sin_t + py * cos_t
                rotated.extend((x, y, pz))
                xy.append((x, y))
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                min_z = min(min_z, pz)
                max_z = max(max_z, pz)
                top = max(top, pz)

            accumulator.add(rotated, faces)
            triangles += len(faces) // 3

            footprint = _element_footprint(xy)
            if footprint is not None:
                accumulator.storey_shapes.setdefault(storey_label, []).append(footprint)
                key = (building_key, storey_label)
                storey_tops[key] = max(storey_tops.get(key, -math.inf), top)

            if not iterator.next():
                break
    else:
        raise ValueError("IfcOpenShell could not triangulate this file — it may be corrupt.")

    if not accumulators or min_x is math.inf:
        raise ValueError("Geometry was found but produced no triangles — nothing to simulate.")

    # --- geographic anchoring ------------------------------------------------
    #
    # With a georeferenced IfcSite the model sits where the surveyor put it, so
    # the working frame keeps the project origin. Without one, the model can be
    # kilometres from origin (Revit survey points routinely are), so we centre
    # the building extent on the project's stated location instead of dropping
    # it in the sea.
    reference = _site_reference(model)
    georeferenced = reference is not None
    if georeferenced:
        origin_lat, origin_lon = reference
        shift_x = shift_y = 0.0
    else:
        origin_lat, origin_lon = fallback_latitude, fallback_longitude
        shift_x = (min_x + max_x) / 2
        shift_y = (min_y + max_y) / 2
        warnings.append(
            "IFC has no IfcSite geolocation — the model was centred on the project location. "
            "Set Revit's survey point and re-export for a georeferenced site."
        )

    origin = GeoAnchor(latitude=origin_lat, longitude=origin_lon)
    bbox = (min_x - shift_x, min_y - shift_y, max_x - shift_x, max_y - shift_y)
    polygon = site_polygon(origin, bbox, buffer_m)

    width_m, height_m = polygon_span_m(polygon)
    if max(width_m, height_m) > MAX_SITE_SPAN_M:
        warnings.append(
            f"Site spans {width_m:.0f} x {height_m:.0f} m — larger than one 512 m tile, "
            "this edition supports single-tile sites only."
        )

    # --- translate into the buildings frame ---------------------------------
    # Origin = polygon bbox SW corner, Z = 0 at the lowest point of the model.
    sw_x = bbox[0] - buffer_m
    sw_y = bbox[1] - buffer_m
    ground_z = min_z

    meshes: dict[str, dict[str, Any]] = {}
    footprints: list[ScenePart] = []
    for mesh_index, (building_key, accumulator) in enumerate(sorted(accumulators.items())):
        coordinates = accumulator.coordinates
        for i in range(0, len(coordinates), 3):
            coordinates[i] = round(coordinates[i] - shift_x - sw_x, 4)
            coordinates[i + 1] = round(coordinates[i + 1] - shift_y - sw_y, 4)
            coordinates[i + 2] = round(coordinates[i + 2] - ground_z, 4)
        meshes[building_key] = {
            "mesh_id": mesh_index,
            "coordinates": coordinates,
            "indices": accumulator.indices,
        }

        for storey_label, shapes in accumulator.storey_shapes.items():
            top = storey_tops.get((building_key, storey_label))
            if top is None:
                continue
            merged = unary_union(shapes)
            parts = merged.geoms if isinstance(merged, MultiPolygon) else [merged]
            for part in parts:
                if part.is_empty or part.area < MIN_FOOTPRINT_AREA_M2:
                    continue
                simplified = part.simplify(0.3, preserve_topology=True)
                ring = [
                    list(origin.to_lonlat(x - shift_x, y - shift_y))
                    for x, y in simplified.exterior.coords
                ]
                footprints.append(ScenePart(polygon=ring, height=max(0.5, top - ground_z)))

    if triangles > MAX_TRIANGLES_PER_BUILDING:
        warnings.append(
            f"{triangles:,} triangles submitted — large models slow the upload and the run. "
            "Exporting only the exterior envelope keeps runs fast."
        )

    return ParsedModel(
        meshes=meshes,
        footprints=footprints,
        polygon=polygon,
        georeferenced=georeferenced,
        stats={
            "buildings": len(meshes),
            "elements": len(elements),
            "triangles": triangles,
            "footprint_parts": len(footprints),
            "site_width_m": round(width_m, 1),
            "site_height_m": round(height_m, 1),
            "model_height_m": round(max_z - min_z, 2),
            "schema": model.schema,
        },
        warnings=warnings,
    )
