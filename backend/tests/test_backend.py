"""Backend tests — everything except the paid Infrared round trip.

`dispatch.run` is the only thing stubbed: it is the call that costs tokens and
needs the network. Payload construction, weather filtering, IFC parsing and
the whole result pipeline run for real.
"""

from __future__ import annotations

from pathlib import Path

import catalog
import dispatch
import ifc_to_dotbim
import main
import numpy as np
import polygon as polygon_lib
import projects
import pytest
import results as results_lib
import weather as weather_lib
from fastapi.testclient import TestClient

from tests.make_fixture_ifc import build as build_fixture

FIXTURE = Path(__file__).parent / "fixture.ifc"


@pytest.fixture(scope="session")
def fixture_ifc() -> Path:
    if not FIXTURE.exists():
        build_fixture(FIXTURE)
    return FIXTURE


@pytest.fixture(scope="session")
def parsed(fixture_ifc: Path) -> ifc_to_dotbim.ParsedModel:
    return ifc_to_dotbim.parse(
        fixture_ifc, fallback_latitude=10.0, fallback_longitude=20.0
    )


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def project(client):
    created = client.post("/projects", json={"name": "Test project"}).json()
    yield created
    projects.delete(created["id"])


# --- geometry / polygon ---------------------------------------------------


def test_polygon_span_is_square_for_a_square_site(parsed):
    width, height = polygon_lib.polygon_span_m(parsed.polygon)
    # 24 m of building plus a 50 m buffer on each side, both directions.
    assert width == pytest.approx(124, abs=1)
    assert height == pytest.approx(124, abs=1)


def test_polygon_ring_is_closed_and_counter_clockwise(parsed):
    ring = parsed.polygon["coordinates"][0]
    assert ring[0] == ring[-1]
    assert polygon_lib._signed_area(ring) > 0


def test_validate_rejects_swapped_coordinates():
    swapped = {"type": "Polygon", "coordinates": [[[10.0, 20.0], [10.1, 20.0], [10.1, 20.1], [10.0, 20.0]]]}
    # An in-range latitude is also a valid longitude, so this one passes — but a
    # latitude of 135 cannot be anything other than a swap.
    bad = {"type": "Polygon", "coordinates": [[[33.0, 135.0], [34.0, 135.0], [34.0, 136.0], [33.0, 135.0]]]}
    polygon_lib.validate(swapped)
    with pytest.raises(ValueError, match="longitude, latitude"):
        polygon_lib.validate(bad)


def test_validate_rejects_multipolygon_and_holes():
    with pytest.raises(ValueError, match="MultiPolygon"):
        polygon_lib.validate({"type": "MultiPolygon", "coordinates": []})
    ring = [[20.0, 10.0], [20.1, 10.0], [20.1, 10.1], [20.0, 10.0]]
    with pytest.raises(ValueError, match="holes"):
        polygon_lib.validate({"type": "Polygon", "coordinates": [ring, ring]})


def test_ifc_parse_reads_geolocation_and_massing(parsed):
    assert parsed.georeferenced is True
    assert parsed.stats["buildings"] == 1
    assert parsed.stats["model_height_m"] == pytest.approx(23.4, abs=0.1)
    # One footprint per storey: the L-shaped podium and the tower above it.
    heights = sorted(round(f.height, 1) for f in parsed.footprints)
    assert heights == [5.4, 23.4]
    # The L-shaped storey must survive as an L, not collapse to its hull.
    podium = min(parsed.footprints, key=lambda f: f.height)
    assert len(podium.polygon) - 1 == 6


def test_building_coordinates_sit_in_the_polygon_sw_frame(parsed):
    coordinates = next(iter(parsed.meshes.values()))["coordinates"]
    xs, ys, zs = coordinates[0::3], coordinates[1::3], coordinates[2::3]
    # Origin is the polygon bbox SW corner, so the building starts one
    # buffer-width in, and Z is measured from the lowest point of the model.
    assert min(xs) == pytest.approx(50, abs=0.5)
    assert min(ys) == pytest.approx(50, abs=0.5)
    assert min(zs) == pytest.approx(0, abs=0.01)


# --- catalog --------------------------------------------------------------


def test_every_analysis_has_defaults_that_coerce():
    for definition in catalog.CATALOG:
        params = catalog.coerce_params(definition.id, None)
        assert set(params) == {p.key for p in definition.params}


def test_slider_values_are_clamped_not_rejected():
    params = catalog.coerce_params("wind-speed", {"wind_speed": 999, "wind_direction": -20})
    assert params["wind_speed"] == 50
    assert params["wind_direction"] == 0


def test_unknown_parameters_and_bad_selects_are_rejected():
    with pytest.raises(ValueError, match="unknown parameter"):
        catalog.coerce_params("wind-speed", {"roughness": 0.25})
    with pytest.raises(ValueError, match="not one of"):
        catalog.coerce_params("pedestrian-wind-comfort", {"criteria": "lawson-1999"})


# --- weather --------------------------------------------------------------


def test_time_period_cascade_matches_the_hour_count():
    weather_file = weather_lib.get("synthetic")
    params = catalog.coerce_params("thermal-comfort-index", None)
    period = dispatch.time_period(params)
    points = weather_lib.filter_weather_data(weather_file, period)
    days = period.end_day - period.start_day + 1
    hours = period.end_hour - period.start_hour + 1
    # The cascade is a cross-product of months x days x hours, not a
    # continuous span — 28 days of 9 hours is 252 rows, not 28 x 24.
    assert len(points) == days * hours


def test_time_period_clamps_impossible_days():
    period = dispatch.time_period(
        {"month": 2, "start_day": 1, "end_day": 31, "start_hour": 9, "end_hour": 17}
    )
    assert (period.start_month, period.end_month) == (2, 2)
    assert period.end_day == 29


def test_zero_length_window_is_refused():
    with pytest.raises(ValueError, match="zero-length"):
        dispatch.time_period(
            {"month": 6, "start_day": 3, "end_day": 3, "start_hour": 9, "end_hour": 9}
        )


def test_epw_covers_a_full_year():
    rows = weather_lib.read_rows(weather_lib.get("synthetic"))
    assert len(rows) == 8760
    assert rows[0][:3] == (1, 1, 0)
    assert rows[-1][:3] == (12, 31, 23)


# --- payload construction -------------------------------------------------


@pytest.mark.parametrize("analysis_id", [a.id for a in catalog.CATALOG])
def test_every_analysis_builds_a_valid_payload(analysis_id):
    weather_file = weather_lib.get("synthetic")
    params = catalog.coerce_params(analysis_id, None)
    payload, hours = dispatch.build_payload(
        analysis_id, params, latitude=10.0, longitude=20.0, weather_file=weather_file
    )
    body = payload.to_dict()
    assert body["analysis-type"] == analysis_id

    definition = catalog.get(analysis_id)
    if definition.needs_weather:
        assert hours > 0
        # Weather arrays must be the same length as each other, or the
        # inference layer fails on a sun-vector mismatch.
        lengths = {len(v) for v in body.values() if isinstance(v, list) and v and isinstance(v[0], float)}
        assert lengths == {hours}
    if "time-period" in body:
        # The sun-vector generator honours one month per run.
        assert body["time-period"]["start-month"] == body["time-period"]["end-month"]


def test_pwc_sends_weather_arrays_but_no_time_period():
    # PWC's window is a weather filter only — the payload itself carries the
    # filtered wind arrays, and adding a time_period would be rejected by the
    # payload's extra="forbid" config.
    payload, hours = dispatch.build_payload(
        "pedestrian-wind-comfort",
        catalog.coerce_params("pedestrian-wind-comfort", None),
        latitude=10.0,
        longitude=20.0,
        weather_file=weather_lib.get("synthetic"),
    )
    body = payload.to_dict()
    assert "time-period" not in body
    assert len(body["wind-speed"]) == len(body["wind-direction"]) == hours


def test_wind_speed_keeps_its_fractional_value():
    payload, _ = dispatch.build_payload(
        "wind-speed",
        catalog.coerce_params("wind-speed", {"wind_speed": 3.5, "wind_direction": 180}),
        latitude=10.0,
        longitude=20.0,
        weather_file=None,
    )
    # Speed scales the whole field linearly — rounding 3.5 to 4 would move
    # every cell by 14%.
    assert payload.wind_speed == 3.5
    assert payload.wind_direction == 180


def test_weather_analyses_refuse_to_run_without_a_file():
    params = catalog.coerce_params("solar-radiation", None)
    with pytest.raises(ValueError, match="needs a weather file"):
        dispatch.build_payload(
            "solar-radiation", params, latitude=10.0, longitude=20.0, weather_file=None
        )


# --- results --------------------------------------------------------------


def _synthetic_grid(rows: int = 40, cols: int = 60) -> np.ndarray:
    grid = np.fromfunction(lambda r, c: r / rows * 6 + c / cols * 2, (rows, cols), dtype=float)
    grid[0, :] = np.nan  # cells outside the polygon
    grid[:, 0] = np.nan
    return grid


def test_nan_cells_are_excluded_from_statistics():
    grid = _synthetic_grid()
    kpis = {k["key"]: k["value"] for k in results_lib.kpis("wind-speed", grid, days_in_window=1, hours_in_window=0)}
    valid = grid[np.isfinite(grid)]
    assert kpis["mean_speed"] == pytest.approx(float(valid.mean()), abs=0.01)
    assert kpis["max_speed"] == pytest.approx(float(valid.max()), abs=0.01)


def test_heatmap_is_transparent_outside_the_polygon_and_north_up():
    import io

    from PIL import Image

    grid = _synthetic_grid()
    image = Image.open(io.BytesIO(results_lib.heatmap_png(grid, 0.0, 8.0)))
    assert image.size == (grid.shape[1], grid.shape[0])
    # Grid row 0 is the south edge and it is NaN, so the BOTTOM image row is
    # the transparent one after the flip.
    assert image.getpixel((10, image.height - 1))[3] == 0
    assert image.getpixel((10, 0))[3] == 255


def test_histogram_bins_span_the_legend_range():
    bins = results_lib.histogram(_synthetic_grid(), 0.0, 8.0)
    assert len(bins) == results_lib.HISTOGRAM_BINS
    assert bins[0]["min"] == 0.0
    assert bins[-1]["max"] == 8.0
    assert sum(b["count"] for b in bins) > 0


# --- API ------------------------------------------------------------------


def test_health_and_catalog_endpoints(client):
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["weather_files"] >= 1

    analyses = client.get("/analyses").json()
    assert [a["id"] for a in analyses] == [a.id for a in catalog.CATALOG]


def test_upload_rejects_non_ifc(client, project):
    response = client.post(
        f"/projects/{project['id']}/upload",
        files={"file": ("model.rvt", b"not ifc", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "IFC" in response.json()["detail"]


def test_run_before_upload_is_refused(client, project):
    response = client.post(
        f"/projects/{project['id']}/run",
        json={"analysis": "sky-view-factors", "params": {}},
    )
    assert response.status_code in (409, 503)


def test_full_workflow(client, project, fixture_ifc, monkeypatch):
    project_id = project["id"]

    upload = client.post(
        f"/projects/{project_id}/upload",
        files={"file": (fixture_ifc.name, fixture_ifc.read_bytes(), "application/octet-stream")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["stats"]["buildings"] == 1
    assert len(body["building"]) == 2  # one extruded outline per storey

    weather_files = client.get(f"/projects/{project_id}/weather").json()
    assert any(w["id"] == "synthetic" for w in weather_files)

    site = client.get(f"/projects/{project_id}/polygon").json()
    assert site["source"] == "auto"
    assert site["width_m"] == pytest.approx(124, abs=1)

    grid = _synthetic_grid()

    def fake_run(analysis_id, params, **kwargs):
        assert kwargs["meshes"], "buildings must reach the SDK"
        return dispatch.RunOutcome(
            grid=grid,
            bounds=(20.00, 10.00, 20.01, 10.01),
            min_legend=0.0,
            max_legend=8.0,
            succeeded_jobs=1,
            total_jobs=1,
            failed_jobs=[],
            hours_in_window=252,
        )

    monkeypatch.setattr(main.dispatch, "run", fake_run)
    monkeypatch.setattr(main, "api_key_configured", lambda: True)

    run = client.post(
        f"/projects/{project_id}/run",
        json={
            "analysis": "wind-speed",
            "weather_id": "synthetic",
            "params": {"wind_speed": 4.5, "wind_direction": 270},
        },
    )
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["params"] == {"wind_speed": 4.5, "wind_direction": 270}
    assert payload["valueRange"] == [0.0, 8.0]
    assert len(payload["kpis"]) == 3
    assert payload["heatmap"]["bounds"] == [[20.0, 10.0], [20.01, 10.01]]
    assert payload["contourPoints"]

    image = client.get(f"/projects/{project_id}/results/{payload['run_id']}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"

    cached = client.get(f"/projects/{project_id}/results").json()
    assert cached["run_id"] == payload["run_id"]

    refreshed = client.get(f"/projects/{project_id}").json()
    assert refreshed["analysisCount"] == 1
    assert refreshed["modelUploaded"] is True


def test_manual_polygon_override_survives_a_reupload(client, project, fixture_ifc):
    project_id = project["id"]
    client.post(
        f"/projects/{project_id}/upload",
        files={"file": (fixture_ifc.name, fixture_ifc.read_bytes(), "application/octet-stream")},
    )
    manual = {
        "type": "Polygon",
        "coordinates": [[[20.000, 10.000], [20.003, 10.000], [20.003, 10.003], [20.000, 10.003], [20.000, 10.000]]],
    }
    response = client.put(f"/projects/{project_id}/polygon", json={"polygon": manual})
    assert response.status_code == 200
    assert response.json()["source"] == "manual"

    client.post(
        f"/projects/{project_id}/upload",
        files={"file": (fixture_ifc.name, fixture_ifc.read_bytes(), "application/octet-stream")},
    )
    after = client.get(f"/projects/{project_id}/polygon").json()
    assert after["source"] == "manual"
    assert after["polygon"]["coordinates"] == manual["coordinates"]
