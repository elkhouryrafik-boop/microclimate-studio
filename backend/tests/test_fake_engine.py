"""Fake engine: all 8 analyses, shape, finiteness, determinism, engine switch, demo, manifest, rename guard."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import catalog
import config
import dispatch
import fake_engine
import main
import numpy as np
import polygon as polygon_lib
import pytest
import weather as weather_lib
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_IDS = [a.id for a in catalog.CATALOG]
LAT, LON = 0.0, 0.0
BOX_INDICES = [
    4, 5, 6, 4, 6, 7, 0, 2, 1, 0, 3, 2, 0, 1, 5, 0, 5, 4,
    1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7,
]  # fmt: skip


def _box(x0, y0, x1, y1, h):
    coords = []
    for z in (0.0, h):
        coords += [x0, y0, z, x1, y0, z, x1, y1, z, x0, y1, z]
    return {"coordinates": coords, "indices": BOX_INDICES}


@pytest.fixture(scope="module")
def scene():
    """A 120 m square site (SW-anchored metres) with two boxes."""
    anchor = polygon_lib.GeoAnchor(latitude=LAT, longitude=LON)
    ring = [list(anchor.to_lonlat(x, y)) for x, y in [(0, 0), (120, 0), (120, 120), (0, 120), (0, 0)]]
    polygon = {"type": "Polygon", "coordinates": [ring]}
    return polygon, {"a": _box(20, 20, 50, 50, 30.0), "b": _box(70, 60, 100, 100, 15.0)}


def _run(analysis_id, scene, **overrides):
    polygon, meshes = scene
    weather_file = weather_lib.get("synthetic") if catalog.get(analysis_id).needs_weather else None
    params = catalog.coerce_params(analysis_id, overrides)
    return fake_engine.run(
        analysis_id,
        params,
        polygon=polygon,
        meshes=meshes,
        latitude=LAT,
        longitude=LON,
        weather_file=weather_file,
        hours_in_window=1,
    )


def test_catalog_has_eight_analyses():
    assert len(ANALYSIS_IDS) == 8


@pytest.mark.parametrize("analysis_id", ANALYSIS_IDS)
def test_fake_grid_is_2d_finite_outside_buildings(analysis_id, scene):
    out = _run(analysis_id, scene)
    assert out.engine == "fake"
    assert out.grid.ndim == 2 and min(out.grid.shape) >= 2
    finite = np.isfinite(out.grid)
    assert finite.any()
    assert (~finite).any(), "building footprints must be NaN"
    assert not np.isinf(out.grid).any()


@pytest.mark.parametrize("analysis_id", ANALYSIS_IDS)
def test_fake_is_deterministic(analysis_id, scene):
    a, b = _run(analysis_id, scene), _run(analysis_id, scene)
    np.testing.assert_array_equal(a.grid, b.grid)
    assert (a.min_legend, a.max_legend) == (b.min_legend, b.max_legend)


@pytest.mark.parametrize("analysis_id", ANALYSIS_IDS)
def test_fake_legend_is_ordered_and_job_counts_match(analysis_id, scene):
    out = _run(analysis_id, scene)
    assert out.min_legend < out.max_legend
    assert out.succeeded_jobs == out.total_jobs == 1 and out.failed_jobs == []


def test_grid_bounds_match_polygon(scene):
    out = _run("sky-view-factors", scene)
    west, south, east, north = out.bounds
    assert west == pytest.approx(LON, abs=1e-9) and south == pytest.approx(LAT, abs=1e-9)
    assert east > west and north > south


def test_sky_view_factor_range_and_variation(scene):
    out = _run("sky-view-factors", scene)
    assert 0.0 <= np.nanmin(out.grid) < np.nanmax(out.grid) <= 100.0


def test_wind_speed_reacts_to_parameter(scene):
    slow = _run("wind-speed", scene, wind_speed=2)
    fast = _run("wind-speed", scene, wind_speed=10)
    assert np.nanmean(fast.grid) > np.nanmean(slow.grid)


def test_wind_wake_is_slower_than_free_stream(scene):
    out = _run("wind-speed", scene, wind_speed=8)
    assert np.nanmin(out.grid) < 8.0


def test_sun_position_noon_equator_equinox_is_overhead():
    el, _ = fake_engine.sun_position(0.0, 80, 12.0)
    assert el > 85.0


def test_sun_below_horizon_at_midnight():
    el, _ = fake_engine.sun_position(30.0, 172, 0.0)
    assert el < 0


def test_height_field_rasterises_boxes():
    h = fake_engine.height_field({"a": _box(10, 10, 30, 30, 12.0)}, 20, 20, 2.0)
    assert h.max() == pytest.approx(12.0)
    assert h[0, 0] == 0.0
    assert (h > 0).sum() > 20


def test_unknown_analysis_raises():
    params = catalog.coerce_params("direct-sun-hours", {})
    weather_file = weather_lib.get("synthetic")
    with pytest.raises(ValueError):
        fake_engine._compute("nope", params, np.zeros((4, 4)), 2.0, LAT, weather_file)


# --- engine switch ---------------------------------------------------------


def test_switch_explicit_fake_wins_over_key(monkeypatch):
    monkeypatch.setenv("MCS_ENGINE", "fake")
    monkeypatch.setenv("INFRARED_API_KEY", "some-value")
    assert config.engine() == "fake"


def test_switch_explicit_infrared(monkeypatch):
    monkeypatch.setenv("MCS_ENGINE", "infrared")
    monkeypatch.delenv("INFRARED_API_KEY", raising=False)
    assert config.engine() == "infrared"


def test_switch_defaults_to_fake_without_key(monkeypatch):
    monkeypatch.delenv("MCS_ENGINE", raising=False)
    monkeypatch.delenv("INFRARED_API_KEY", raising=False)
    assert config.engine() == "fake"


def test_switch_placeholder_key_is_not_a_key(monkeypatch):
    monkeypatch.delenv("MCS_ENGINE", raising=False)
    monkeypatch.setenv("INFRARED_API_KEY", "your_api_key_here")
    assert config.engine() == "fake"


def test_switch_key_selects_infrared(monkeypatch):
    monkeypatch.delenv("MCS_ENGINE", raising=False)
    monkeypatch.setenv("INFRARED_API_KEY", "abc")
    assert config.engine() == "infrared"


def test_switch_garbage_value_falls_back(monkeypatch):
    monkeypatch.setenv("MCS_ENGINE", "gpu")
    monkeypatch.delenv("INFRARED_API_KEY", raising=False)
    assert config.engine() == "fake"


def test_health_reports_synthetic(monkeypatch):
    monkeypatch.setenv("MCS_ENGINE", "fake")
    body = TestClient(main.app).get("/health").json()
    assert body["engine"] == "fake" and body["synthetic"] is True


def test_dispatch_run_uses_fake_without_network(monkeypatch, scene):
    monkeypatch.setenv("MCS_ENGINE", "fake")
    monkeypatch.setattr(dispatch, "InfraredClient", lambda *a, **k: pytest.fail("real client constructed"))
    polygon, meshes = scene
    out = dispatch.run(
        "wind-speed",
        catalog.coerce_params("wind-speed", {}),
        polygon=polygon,
        meshes=meshes,
        latitude=LAT,
        longitude=LON,
        weather_file=None,
    )
    assert out.engine == "fake"


# --- demo smoke ------------------------------------------------------------


def test_demo_runs_all_eight_and_labels_synthetic(tmp_path):
    out_dir = tmp_path / "d"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "backend" / "demo.py"), "--out", str(out_dir)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
        env={**os.environ, "MCS_ENGINE": "fake", "INFRARED_API_KEY": ""},
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["engine"] == "fake" and summary["synthetic"] is True
    assert set(summary["analyses"]) == set(ANALYSIS_IDS)
    assert all(a["engine"] == "fake" for a in summary["analyses"].values())
    pngs = sorted(out_dir.glob("*.png"))
    assert len(pngs) == 8
    assert pngs[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# --- manifest schema -------------------------------------------------------

MANIFEST = yaml.safe_load((ROOT / "weather_data" / "weather_manifest.yaml").read_text(encoding="utf-8"))["files"]


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["id"] for e in MANIFEST])
def test_manifest_entry_schema(entry):
    for key in ("id", "filename", "source_url", "sha256", "licence_note", "vetted_by", "latitude", "longitude"):
        assert entry.get(key) not in (None, ""), key
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert entry["filename"].endswith(".epw")
    assert -90 <= entry["latitude"] <= 90 and -180 <= entry["longitude"] <= 180


def test_manifest_ids_unique():
    ids = [e["id"] for e in MANIFEST]
    assert len(ids) == len(set(ids))


def test_manifest_vetted_by_is_generic():
    assert {e["vetted_by"] for e in MANIFEST} == {"maintainer"}


def test_no_epw_files_are_shipped_in_weather_data():
    assert not list((ROOT / "weather_data").glob("*.epw"))


# --- rename guard ----------------------------------------------------------

SKIP_DIRS = {".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache", "cache", "out", ".git"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".html", ".md", ".yaml", ".yml", ".toml", ".txt", ".example"}


def _repo_text_files():
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
            continue
        if set(p.relative_to(ROOT).parts) & SKIP_DIRS or p.name == Path(__file__).name:
            continue
        yield p


def _hits(pattern):
    rx = re.compile(pattern)
    return [
        str(p.relative_to(ROOT))
        for p in _repo_text_files()
        if rx.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]


def test_env_vars_use_mcs_prefix():
    names = set()
    for p in (ROOT / "backend").glob("*.py"):
        names |= set(re.findall(r'getenv\("([A-Z_]+)"', p.read_text(encoding="utf-8")))
    assert names, "expected env lookups"
    assert all(n.startswith("MCS_") or n == "INFRARED_API_KEY" for n in names), names


def test_env_example_has_no_values():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            assert line.split("=", 1)[1].strip() == "", line


def test_no_absolute_personal_paths():
    drive_users = "C:" + "\\\\" + "Users" + "\\\\"
    posix_users = "/" + "c/Users/"
    assert not _hits("(?i)" + drive_users + "|" + posix_users + "|One" + "Drive")
