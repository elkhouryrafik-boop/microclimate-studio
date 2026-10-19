"""Site polygon derivation and the local-metre <-> lon/lat conversions.

Two coordinate frames are in play and mixing them is the classic Infrared bug:

* **Site metres** — X east, Y north, Z up, origin at the SW corner of the site
  polygon's bounding box. This is what `buildings` must be in.
* **lon/lat (EPSG:4326)** — GeoJSON order `[longitude, latitude]` (RFC 7946).
  This is what the polygon, vegetation and the frontend scene use.

Over a site of a few hundred metres an equirectangular conversion around a
fixed anchor is accurate to well under a metre, so no projection library is
needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_METERS_PER_DEGREE_LAT = 111_320.0


@dataclass(frozen=True)
class GeoAnchor:
    """Ties one point in the local metre frame to a geographic position."""

    latitude: float
    longitude: float

    @property
    def meters_per_degree_lon(self) -> float:
        # Guard the cos() term so a pathological latitude cannot divide by ~0.
        return EARTH_METERS_PER_DEGREE_LAT * max(0.01, math.cos(math.radians(self.latitude)))

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.longitude + x / self.meters_per_degree_lon,
            self.latitude + y / EARTH_METERS_PER_DEGREE_LAT,
        )

    def to_meters(self, lon: float, lat: float) -> tuple[float, float]:
        return (
            (lon - self.longitude) * self.meters_per_degree_lon,
            (lat - self.latitude) * EARTH_METERS_PER_DEGREE_LAT,
        )


def ring_from_bbox(
    anchor: GeoAnchor,
    bbox: tuple[float, float, float, float],
    buffer_m: float,
) -> list[list[float]]:
    """Closed CCW `[lon, lat]` ring around a metre-space bbox, buffered outward."""
    min_x, min_y, max_x, max_y = bbox
    min_x -= buffer_m
    min_y -= buffer_m
    max_x += buffer_m
    max_y += buffer_m
    corners = [
        (min_x, min_y),  # SW — counter-clockwise from here
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]
    ring = [list(anchor.to_lonlat(x, y)) for x, y in corners]
    ring.append(list(ring[0]))
    return ring


def site_polygon(
    anchor: GeoAnchor,
    bbox: tuple[float, float, float, float],
    buffer_m: float,
) -> dict:
    return {"type": "Polygon", "coordinates": [ring_from_bbox(anchor, bbox, buffer_m)]}


def polygon_bounds(polygon: dict) -> tuple[float, float, float, float]:
    """`(west, south, east, north)` of a GeoJSON polygon's outer ring."""
    ring = polygon["coordinates"][0]
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return min(lons), min(lats), max(lons), max(lats)


def polygon_span_m(polygon: dict) -> tuple[float, float]:
    """Width and height of the polygon bbox in metres."""
    west, south, east, north = polygon_bounds(polygon)
    # Measure from the SW corner, and take the degree-to-metre factor for
    # longitude at mid-latitude so the width is not biased by the edge.
    anchor = GeoAnchor(latitude=south, longitude=west)
    mid = GeoAnchor(latitude=(south + north) / 2, longitude=west)
    width = (east - west) * mid.meters_per_degree_lon
    _, height = anchor.to_meters(west, north)
    return width, height


def sw_anchor(polygon: dict) -> GeoAnchor:
    """Anchor at the polygon bbox SW corner — the origin of the buildings frame."""
    west, south, _, _ = polygon_bounds(polygon)
    return GeoAnchor(latitude=south, longitude=west)


def validate(polygon: dict) -> dict:
    """Check the SDK's polygon rules early, with messages naming the fix.

    The SDK validates again before tiling; catching it here means the user sees
    the problem on the polygon editor rather than 30 s into a run.
    """
    if not isinstance(polygon, dict):
        raise ValueError("Polygon must be a GeoJSON object.")
    if polygon.get("type") != "Polygon":
        raise ValueError(
            f"Polygon type must be 'Polygon', got {polygon.get('type')!r}. "
            "MultiPolygon is not supported — split it into separate runs."
        )
    rings = polygon.get("coordinates") or []
    if len(rings) != 1:
        raise ValueError("Polygon must have exactly one ring — holes are not supported.")
    ring = rings[0]
    if len(ring) < 4:
        raise ValueError("Polygon ring needs at least 3 unique vertices plus the closing vertex.")
    for lon, lat in ring:
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise ValueError(
                f"Coordinate ({lon}, {lat}) is out of range — GeoJSON order is [longitude, latitude]."
            )
    if ring[0] != ring[-1]:
        ring = [*ring, ring[0]]

    if _signed_area(ring) < 0:  # SDK normalises this, but keep our copy canonical
        ring = list(reversed(ring))
    return {"type": "Polygon", "coordinates": [ring]}


def _signed_area(ring: list[list[float]]) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        total += x0 * y1 - x1 * y0
    return total / 2.0


def centroid(polygon: dict) -> tuple[float, float]:
    """`(longitude, latitude)` of the polygon bbox centre."""
    west, south, east, north = polygon_bounds(polygon)
    return (west + east) / 2, (south + north) / 2
