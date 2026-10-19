"""Offline demo: run all 8 analyses on the synthetic sample site.

    python backend/demo.py --out out/demo

Creates a project, uploads examples/sample-site.ifc, selects the generated
`synthetic` weather file, runs every analysis and writes `<analysis>.png`
plus `summary.json` (KPIs per analysis) into --out. No key, no network.

The engine defaults to the synthetic "fake" engine (set before config loads,
so a key in .env is never used by accident). To exercise the real SDK path
deliberately: `MCS_ENGINE=infrared python backend/demo.py` (costs API tokens).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("MCS_ENGINE", "fake")

import catalog  # noqa: E402
import main  # noqa: E402
import projects  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SAMPLE_IFC = ROOT / "examples" / "sample-site.ifc"
WEATHER_ID = "synthetic"


def run_demo(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    client = TestClient(main.app)
    started = time.perf_counter()

    health = client.get("/health").json()
    project = client.post("/projects", json={"name": "Synthetic sample site"}).json()
    pid = project["id"]
    summary: dict = {
        "engine": health["engine"],
        "synthetic": health["synthetic"],
        "weather": WEATHER_ID,
        "model": SAMPLE_IFC.name,
        "analyses": {},
    }
    try:
        upload = client.post(
            f"/projects/{pid}/upload",
            files={"file": (SAMPLE_IFC.name, SAMPLE_IFC.read_bytes(), "application/octet-stream")},
        )
        upload.raise_for_status()

        for definition in catalog.CATALOG:
            analysis_id = definition.id
            response = client.post(
                f"/projects/{pid}/run",
                json={"analysis": analysis_id, "weather_id": WEATHER_ID if definition.needs_weather else None},
            )
            response.raise_for_status()
            result = response.json()
            image = client.get(f"/projects/{pid}/results/{result['run_id']}/image")
            image.raise_for_status()
            (out / f"{analysis_id}.png").write_bytes(image.content)
            summary["analyses"][analysis_id] = {
                "engine": result["engine"],
                "unit": result["unit"],
                "valueRange": result["valueRange"],
                "params": result["params"],
                "kpis": result["kpis"],
                "grid_shape": result["metadata"]["grid_shape"],
            }
            print(f"{analysis_id:28s} engine={result['engine']} kpis={[k['value'] for k in result['kpis']]}")
    finally:
        projects.delete(pid)

    summary["duration_s"] = round(time.perf_counter() - started, 1)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main_cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="out/demo", help="output directory")
    args = parser.parse_args()
    summary = run_demo(Path(args.out))
    print(f"wrote {len(summary['analyses'])} PNGs + summary.json to {args.out} in {summary['duration_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
