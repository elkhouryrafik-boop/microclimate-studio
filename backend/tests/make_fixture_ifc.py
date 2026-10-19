"""Generate a small georeferenced IFC so the parse path can be tested offline.

Builds an L-shaped two-storey block: a podium slab, four podium walls and a
smaller upper mass. Enough shape that the footprint union has to do real work
(an L is not its own convex hull) and enough structure that the
building/storey containment logic is exercised.

    python tests/make_fixture_ifc.py [output.ifc]
"""

from __future__ import annotations

import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.util.shape_builder

# Arbitrary reference coordinates (synthetic site, no real-world meaning).
# The model itself is synthetic.
SITE_LAT = (10, 0, 0, 0)
SITE_LON = (20, 0, 0, 0)

# (name, IFC class, storey key, origin x/y/z, size width/depth/height)
PARTS = [
    ("Podium slab west", "IfcSlab", "ground", (0.0, 0.0, 0.0), (24.0, 14.0, 0.4)),
    ("Podium slab south", "IfcSlab", "ground", (0.0, 14.0, 0.0), (12.0, 10.0, 0.4)),
    ("Wall north", "IfcWall", "ground", (0.0, 0.0, 0.4), (24.0, 0.3, 5.0)),
    ("Wall east", "IfcWall", "ground", (23.7, 0.0, 0.4), (0.3, 14.0, 5.0)),
    ("Wall west", "IfcWall", "ground", (0.0, 0.0, 0.4), (0.3, 24.0, 5.0)),
    ("Wall south", "IfcWall", "ground", (0.0, 23.7, 0.4), (12.0, 0.3, 5.0)),
    ("Tower", "IfcBuildingElementProxy", "upper", (2.0, 2.0, 5.4), (10.0, 10.0, 18.0)),
]


def build(path: Path) -> Path:
    model = ifcopenshell.file(schema="IFC4")

    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Synthetic fixture")
    # Metres, not the millimetre default — the part dimensions below are metres.
    ifcopenshell.api.unit.assign_unit(
        model, units=[ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT")]
    )
    model_context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )

    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    site.RefLatitude = SITE_LAT
    site.RefLongitude = SITE_LON
    site.RefElevation = 20.0

    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="Block A")
    storeys = {
        "ground": ifcopenshell.api.root.create_entity(
            model, ifc_class="IfcBuildingStorey", name="Ground floor"
        ),
        "upper": ifcopenshell.api.root.create_entity(
            model, ifc_class="IfcBuildingStorey", name="Upper floor"
        ),
    }

    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(
        model, products=list(storeys.values()), relating_object=building
    )

    builder = ifcopenshell.util.shape_builder.ShapeBuilder(model)

    for name, ifc_class, storey_key, (x, y, z), (width, depth, height) in PARTS:
        element = ifcopenshell.api.root.create_entity(model, ifc_class=ifc_class, name=name)
        outline = builder.polyline(
            [(x, y), (x + width, y), (x + width, y + depth), (x, y + depth)], closed=True
        )
        solid = builder.extrude(
            builder.profile(outline), magnitude=height, position=(0.0, 0.0, z)
        )
        representation = builder.get_representation(body, [solid])
        ifcopenshell.api.geometry.assign_representation(
            model, product=element, representation=representation
        )
        ifcopenshell.api.spatial.assign_container(
            model, products=[element], relating_structure=storeys[storey_key]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "fixture.ifc"
    print(build(target))
