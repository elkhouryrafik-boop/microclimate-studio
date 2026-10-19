"""Project storage — one directory per project under `backend/cache/projects/`.

Flat files, no database: a single engineer's project list is small, the data
must survive a restart, and a directory of JSON is something you can inspect
and hand to a colleague. Geometry is gzipped because a parsed tower runs to
tens of MB of vertex floats.

    <project id>/
        project.json        metadata + derived site polygon
        model.ifc           the uploaded export
        geometry.json.gz    DotBim meshes + scene footprints
        results/<run>.json  cached run output (+ .png heatmap)
"""

from __future__ import annotations

import gzip
import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import weather
from config import PROJECTS_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Project:
    id: str
    name: str
    location: str = ""
    description: str = ""
    latitude: float = 10.0  # default: arbitrary placeholder location (no real site)
    longitude: float = 20.0
    createdAt: str = field(default_factory=_now)
    updatedAt: str = field(default_factory=_now)
    analysisCount: int = 0
    lastRunAt: str | None = None

    # model state
    model_name: str | None = None
    polygon: dict | None = None
    polygon_source: str = "auto"  # "auto" from the IFC extent, or "manual"
    georeferenced: bool = False
    model_stats: dict[str, Any] = field(default_factory=dict)
    model_warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["modelUploaded"] = self.model_name is not None
        return payload


def _dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _path(project_id: str) -> Path:
    return _dir(project_id) / "project.json"


def list_projects() -> list[Project]:
    projects: list[Project] = []
    for path in PROJECTS_DIR.glob("*/project.json"):
        try:
            projects.append(Project(**json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, TypeError):
            continue  # a half-written project should not break the list
    projects.sort(key=lambda p: p.updatedAt, reverse=True)
    return projects


def get(project_id: str) -> Project:
    path = _path(project_id)
    if not path.exists():
        raise KeyError(project_id)
    return Project(**json.loads(path.read_text(encoding="utf-8")))


def save(project: Project) -> Project:
    project.updatedAt = _now()
    directory = _dir(project.id)
    directory.mkdir(parents=True, exist_ok=True)
    _path(project.id).write_text(json.dumps(asdict(project), indent=2), encoding="utf-8")
    return project


def create(
    name: str,
    *,
    location: str = "",
    description: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
) -> Project:
    project = Project(id=f"prj-{uuid.uuid4().hex[:10]}", name=name.strip() or "Untitled project")
    project.location = location
    project.description = description
    if latitude is not None:
        project.latitude = latitude
    if longitude is not None:
        project.longitude = longitude
    return save(project)


def delete(project_id: str) -> None:
    shutil.rmtree(_dir(project_id), ignore_errors=True)
    weather.delete_project_weather(project_id)


def model_path(project_id: str) -> Path:
    return _dir(project_id) / "model.ifc"


def geometry_path(project_id: str) -> Path:
    return _dir(project_id) / "geometry.json.gz"


def write_geometry(project_id: str, payload: dict[str, Any]) -> None:
    path = geometry_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)


def read_geometry(project_id: str) -> dict[str, Any]:
    path = geometry_path(project_id)
    if not path.exists():
        raise FileNotFoundError("No parsed geometry — upload an IFC model first.")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# --- run results ----------------------------------------------------------


def results_dir(project_id: str) -> Path:
    path = _dir(project_id) / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_id(analysis: str) -> str:
    return f"{analysis}-{int(time.time() * 1000):x}"


def write_result(project_id: str, result: dict[str, Any], image: bytes | None) -> None:
    directory = results_dir(project_id)
    identifier = result["run_id"]
    if image is not None:
        (directory / f"{identifier}.png").write_bytes(image)
    (directory / f"{identifier}.json").write_text(json.dumps(result), encoding="utf-8")


def read_result(project_id: str, identifier: str) -> dict[str, Any]:
    path = results_dir(project_id) / f"{identifier}.json"
    if not path.exists():
        raise KeyError(identifier)
    return json.loads(path.read_text(encoding="utf-8"))


def result_image_path(project_id: str, identifier: str) -> Path:
    return results_dir(project_id) / f"{identifier}.png"


def list_results(project_id: str) -> list[dict[str, Any]]:
    """Cached runs, newest first."""
    out: list[dict[str, Any]] = []
    for path in results_dir(project_id).glob("*.json"):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    out.sort(key=lambda r: r.get("metadata", {}).get("timestamp", ""), reverse=True)
    return out


def latest_result(project_id: str, analysis: str | None = None) -> dict[str, Any] | None:
    for result in list_results(project_id):
        if analysis is None or result.get("analysis") == analysis:
            return result
    return None


def record_run(project: Project) -> Project:
    project.analysisCount += 1
    project.lastRunAt = _now()
    return save(project)
