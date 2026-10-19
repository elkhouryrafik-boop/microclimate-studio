# Coordinate frames

Two frames are in play, and mixing them is the classic bug.

| Frame | Axes | Used for |
|---|---|---|
| Site metres | X east, Y north, Z up. Origin at the south-west corner of the site polygon's bounding box. | Building meshes sent to the engine |
| lon/lat | GeoJSON order `[longitude, latitude]` (RFC 7946, EPSG:4326) | The site polygon, the deck.gl scene, heatmap bounds |

`backend/polygon.py` converts between them with an equirectangular approximation around one anchor point. Over a site
of a few hundred metres that is accurate to well under a metre, so no projection library is used.

## How a model gets placed

1. `backend/ifc_to_dotbim.py` triangulates the IFC with IfcOpenShell, one mesh per `IfcBuilding`.
2. The site polygon is the building extent plus a buffer (`MCS_SITE_BUFFER_M`, default 50 m).
3. Meshes are shifted so the polygon's south-west corner is the origin.
4. If the IFC has no `IfcSite` georeference, the model is centred on the project location and the upload response
   carries a warning, which the UI shows next to the model. The bundled sample IFC stores a 0, 0 placeholder in its `IfcSite`; the parser treats that as "no georeference", so the sample is centred on the default project location (10°N, 20°E, an arbitrary placeholder point, not a project site) and shows this warning.

## Grid conventions

- Cells outside the polygon are `NaN`, never zero. Zero would drag every statistic down.
- Row 0 is the south edge, column 0 the west edge. Images are top-down, so the array is flipped once on the way to a PNG.
- Colour bounds come from each analysis's legend range, not from the data range.

## Single-tile limit

One tile is 512 x 512 m (`MCS_MAX_SITE_SPAN_M`). Staying inside one tile keeps runs short and avoids seams.
A site that exceeds the limit produces a warning at upload.
