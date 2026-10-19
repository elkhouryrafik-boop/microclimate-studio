"""Synthetic sample data, weather manifest and the EPW fetcher (no network)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import ifc_to_dotbim
import pytest
import weather as weather_lib
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


make_sample = _load("make_sample", EXAMPLES / "make_sample.py")
fetch_weather = _load("fetch_weather", ROOT / "scripts" / "fetch_weather.py")


@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sample")
    make_sample.build_ifc(out / "sample-site.ifc")
    make_sample.build_epw(out / "synthetic.epw")
    return out


def test_make_sample_is_reproducible(sample_dir, tmp_path):
    make_sample.build_ifc(tmp_path / "sample-site.ifc")
    make_sample.build_epw(tmp_path / "synthetic.epw")
    for name in ("sample-site.ifc", "synthetic.epw"):
        assert (tmp_path / name).read_bytes() == (sample_dir / name).read_bytes()


def test_committed_sample_matches_the_generator(sample_dir):
    for name in ("sample-site.ifc", "synthetic.epw"):
        assert (EXAMPLES / name).read_bytes() == (sample_dir / name).read_bytes()


def test_sample_ifc_has_three_buildings_and_synthetic_names():
    parsed = ifc_to_dotbim.parse(EXAMPLES / "sample-site.ifc", fallback_latitude=0.0, fallback_longitude=0.0)
    assert parsed.stats["buildings"] == 3
    text = (EXAMPLES / "sample-site.ifc").read_text(encoding="utf-8")
    assert "Synthetic sample site" in text


def test_synthetic_epw_parses_with_8760_rows():
    wf = weather_lib.get("synthetic")
    assert wf.station_name == "Synthetic"
    rows = weather_lib.read_rows(wf)
    assert len(rows) == 8760
    temps = [r[3]["dryBulbTemperature"] for r in rows]
    assert 10 < min(temps) < 25 < 35 < max(temps) < 50
    assert max(r[3]["globalHorizontalRadiation"] for r in rows) > 500
    assert "not measured data" in (EXAMPLES / "synthetic.epw").read_text(encoding="utf-8").splitlines()[5]


def test_manifest_entries_carry_provenance():
    entries = yaml.safe_load((ROOT / "weather_data" / "weather_manifest.yaml").read_text(encoding="utf-8"))["files"]
    assert len(entries) == 6
    for e in entries:
        assert e["source_url"] and e["licence_note"] and len(e["sha256"]) == 64
        assert e["vetted_by"] == "maintainer"
    synthetic = next(e for e in entries if e["id"] == "synthetic")
    digest = hashlib.sha256((EXAMPLES / "synthetic.epw").read_bytes()).hexdigest()
    assert synthetic["sha256"] == digest


# --- fetcher (mocked download) --------------------------------------------


def _zip_of(epw: bytes, name: str = "x.epw") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, epw)
        zf.writestr("x.stat", b"ignored")
    return buf.getvalue()


def _entry(epw: bytes, sha: str | None = None) -> dict:
    return {
        "id": "demo",
        "filename": "demo.epw",
        "source_url": "https://example.invalid/demo.zip",
        "sha256": sha or hashlib.sha256(epw).hexdigest(),
    }


def test_fetch_writes_verified_epw(tmp_path):
    epw = b"LOCATION,Fake\n"
    calls = []

    def download(url):
        calls.append(url)
        return _zip_of(epw)

    path = fetch_weather.fetch_entry(_entry(epw), tmp_path, download)
    assert path.read_bytes() == epw
    # a verified file is not downloaded again
    fetch_weather.fetch_entry(_entry(epw), tmp_path, download)
    assert len(calls) == 1


def test_fetch_checksum_mismatch_is_an_error_and_writes_nothing(tmp_path):
    entry = _entry(b"expected", sha="0" * 64)
    with pytest.raises(fetch_weather.ChecksumMismatch):
        fetch_weather.fetch_entry(entry, tmp_path, lambda url: _zip_of(b"tampered"))
    assert not (tmp_path / "demo.epw").exists()


def test_fetch_rejects_non_zip_and_zero_epw(tmp_path):
    with pytest.raises(fetch_weather.FetchError):
        fetch_weather.fetch_entry(_entry(b"a"), tmp_path, lambda url: b"not a zip")
    with pytest.raises(fetch_weather.FetchError):
        fetch_weather.fetch_entry(_entry(b"a"), tmp_path, lambda url: _zip_of(b"a", name="x.txt"))


def test_fetch_cli_exit_codes(tmp_path):
    epw = b"abc"
    manifest = tmp_path / "m.yaml"
    manifest.write_text(yaml.safe_dump({"files": [_entry(epw), {"id": "local", "source_url": "generated:x"}]}))
    dest = tmp_path / "out"
    argv = ["--manifest", str(manifest), "--dest", str(dest)]
    assert fetch_weather.main(["--all", *argv], download=lambda u: _zip_of(epw)) == 0
    assert (dest / "demo.epw").read_bytes() == epw
    assert fetch_weather.main(["--all", "--force", *argv], download=lambda u: _zip_of(b"other")) == 1
    assert fetch_weather.main(["nope", *argv]) == 2
    assert fetch_weather.main(argv) == 2
