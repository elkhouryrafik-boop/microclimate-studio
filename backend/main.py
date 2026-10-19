"""Microclimate Studio — FastAPI backend.

Upload a Revit IFC export, pick a vetted EPW, run an Infrared microclimate
analysis, get back the grid as KPIs, a histogram and a heatmap the DeckGL
scene can drape over the site.

Run it with:

    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import catalog
import dispatch
import ifc_to_dotbim
import numpy as np
import polygon as polygon_lib
import projects
import results as results_lib
import weather as weather_lib
from config import ALLOWED_ORIGINS, SITE_BUFFER_M, api_key_configured, engine
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("mcs.climate")

app = FastAPI(title="Microclimate Studio", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateProject(BaseModel):
    name: str
    location: str = ""
    description: str = ""
    latitude: float | None = None
    longitude: float | None = None


class PolygonOverride(BaseModel):
    polygon: dict


class RunRequest(BaseModel):
    analysis: str
    weather_id: str | None = None
    model_name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    latitude: float | None = None
    longitude: float | None = None


def _project_or_404(project_id: str) -> projects.Project:
    try:
        return projects.get(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No project {project_id!r}") from None


def outcome_engine_label() -> str:
    return "Fake-engine" if engine() == "fake" else "Infrared"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "api_key_configured": api_key_configured(),
        "engine": engine(),
        "synthetic": engine() == "fake",
        "weather_files": len(weather_lib.library()),
    }


@app.get("/analyses")
def analyses() -> list[dict[str, Any]]:
    return catalog.catalog_json()


# --- projects -------------------------------------------------------------


@app.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    return [p.to_json() for p in projects.list_projects()]


@app.post("/projects")
def create_project(body: CreateProject) -> dict[str, Any]:
    project = projects.create(
        body.name,
        location=body.location,
        description=body.description,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return project.to_json()


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    return _project_or_404(project_id).to_json()


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    _project_or_404(project_id)
    projects.delete(project_id)


# --- model upload ---------------------------------------------------------


@app.post("/projects/{project_id}/upload")
def upload_model(project_id: str, file: UploadFile) -> dict[str, Any]:
    project = _project_or_404(project_id)
    filename = file.filename or "model.ifc"
    if not filename.lower().endswith((".ifc", ".ifczip")):
        raise HTTPException(
            status_code=400,
            detail="Upload an IFC export (Revit: File -> Export -> IFC). RVT files are not readable headlessly.",
        )

    target = projects.model_path(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file.file.read())

    started = time.perf_counter()
    try:
        parsed = ifc_to_dotbim.parse(
            target,
            fallback_latitude=project.latitude,
            fallback_longitude=project.longitude,
            buffer_m=SITE_BUFFER_M,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except Exception as err:  # IfcOpenShell raises bare RuntimeErrors on bad files
        logger.exception("IFC parse failed for %s", project_id)
        raise HTTPException(status_code=422, detail=f"Could not read this IFC: {err}") from err

    projects.write_geometry(
        project_id,
        {
            "meshes": parsed.meshes,
            "footprints": [f.to_json() for f in parsed.footprints],
        },
    )

    project.model_name = filename
    project.georeferenced = parsed.georeferenced
    project.model_stats = parsed.stats
    project.model_warnings = parsed.warnings
    if project.polygon_source != "manual":
        project.polygon = parsed.polygon
    if parsed.georeferenced:
        # The IFC knows where it is — trust it over the typed-in location.
        longitude, latitude = polygon_lib.centroid(parsed.polygon)
        project.latitude, project.longitude = latitude, longitude
    projects.save(project)

    logger.info(
        "%s parsed in %.1fs — %s buildings, %s triangles",
        filename,
        time.perf_counter() - started,
        parsed.stats.get("buildings"),
        parsed.stats.get("triangles"),
    )

    return {
        "status": "ok",
        "model_name": filename,
        "building": [f.to_json() for f in parsed.footprints],
        "polygon": parsed.polygon,
        "latitude": project.latitude,
        "longitude": project.longitude,
        "stats": parsed.stats,
        "warnings": parsed.warnings,
        "message": "; ".join(parsed.warnings) or None,
    }


@app.get("/projects/{project_id}/geometry")
def get_geometry(project_id: str) -> dict[str, Any]:
    _project_or_404(project_id)
    try:
        geometry = projects.read_geometry(project_id)
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return {"building": geometry["footprints"]}


# --- site polygon ---------------------------------------------------------


@app.get("/projects/{project_id}/polygon")
def get_polygon(project_id: str) -> dict[str, Any]:
    project = _project_or_404(project_id)
    if not project.polygon:
        raise HTTPException(status_code=404, detail="No site polygon yet — upload an IFC model first.")
    width, height = polygon_lib.polygon_span_m(project.polygon)
    return {
        "polygon": project.polygon,
        "source": project.polygon_source,
        "width_m": round(width, 1),
        "height_m": round(height, 1),
    }


@app.put("/projects/{project_id}/polygon")
def set_polygon(project_id: str, body: PolygonOverride) -> dict[str, Any]:
    project = _project_or_404(project_id)
    try:
        cleaned = polygon_lib.validate(body.polygon)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    project.polygon = cleaned
    project.polygon_source = "manual"
    projects.save(project)
    width, height = polygon_lib.polygon_span_m(cleaned)
    return {"polygon": cleaned, "source": "manual", "width_m": round(width, 1), "height_m": round(height, 1)}


# --- weather --------------------------------------------------------------


@app.get("/projects/{project_id}/weather")
def list_weather(project_id: str) -> list[dict[str, Any]]:
    _project_or_404(project_id)
    return [f.to_json() for f in weather_lib.library(project_id)]


@app.post("/projects/{project_id}/weather")
def upload_weather(project_id: str, file: UploadFile) -> dict[str, Any]:
    _project_or_404(project_id)
    try:
        stored = weather_lib.store_upload(project_id, file.filename or "custom.epw", file.file.read())
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return stored.to_json()


# --- runs -----------------------------------------------------------------


@app.post("/projects/{project_id}/run")
def run_analysis(project_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
    project = _project_or_404(project_id)

    if engine() == "infrared" and not api_key_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "INFRARED_API_KEY is not set — add it to .env, "
                "or set MCS_ENGINE=fake for the synthetic demo engine."
            ),
        )

    try:
        definition = catalog.get(body.analysis)
        params = catalog.coerce_params(body.analysis, body.params)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    if not project.polygon:
        raise HTTPException(status_code=409, detail="Upload an IFC model before running an analysis.")
    try:
        geometry = projects.read_geometry(project_id)
    except FileNotFoundError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err

    weather_file = None
    if body.weather_id:
        try:
            weather_file = weather_lib.get(body.weather_id, project_id)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
    if definition.needs_weather and weather_file is None:
        raise HTTPException(
            status_code=400,
            detail=f"{definition.label} needs a weather file — pick one from the library.",
        )

    latitude = body.latitude if body.latitude is not None else project.latitude
    longitude = body.longitude if body.longitude is not None else project.longitude

    started = time.perf_counter()
    try:
        outcome = dispatch.run(
            body.analysis,
            params,
            polygon=project.polygon,
            meshes=dispatch.to_meshes(geometry),
            latitude=latitude,
            longitude=longitude,
            weather_file=weather_file,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        logger.exception("Analysis %s failed for %s", body.analysis, project_id)
        raise HTTPException(status_code=502, detail=f"{outcome_engine_label()} run failed: {err}") from err
    duration = time.perf_counter() - started

    grid = np.asarray(outcome.grid, dtype=float)
    if grid.ndim != 2 or grid.size == 0:
        raise HTTPException(status_code=502, detail="Infrared returned an empty grid.")

    lo, hi = results_lib.legend_bounds(grid, outcome.min_legend, outcome.max_legend)
    bounds = outcome.bounds or polygon_lib.polygon_bounds(project.polygon)
    west, south, east, north = bounds

    days_in_window = 1
    if definition.needs_time_period:
        period = dispatch.time_period(params)
        days_in_window = period.end_day - period.start_day + 1

    identifier = projects.run_id(body.analysis)
    image = results_lib.heatmap_png(grid, lo, hi)

    payload: dict[str, Any] = {
        "run_id": identifier,
        "analysis": body.analysis,
        "engine": outcome.engine,
        "unit": definition.unit,
        "valueRange": [round(lo, 3), round(hi, 3)],
        "params": params,
        "kpis": results_lib.kpis(
            body.analysis,
            grid,
            days_in_window=days_in_window,
            hours_in_window=outcome.hours_in_window,
        ),
        "histogram": results_lib.histogram(grid, lo, hi),
        "metadata": {
            "station": weather_file.station_name if weather_file else "—",
            "latitude": latitude,
            "longitude": longitude,
            "engine": outcome.engine,
            "analysis": body.analysis,
            "analysis_label": definition.label,
            "weather_file": weather_file.filename if weather_file else "not required",
            "model": project.model_name or body.model_name or "model.ifc",
            "timestamp": _now(),
            "duration_s": round(duration, 1),
            "grid_shape": list(grid.shape),
            "jobs": f"{outcome.succeeded_jobs}/{outcome.total_jobs}",
            "hours_in_window": outcome.hours_in_window,
        },
        "heatmap": {
            "imageUrl": str(request.base_url).rstrip("/")
            + f"/projects/{project_id}/results/{identifier}/image",
            "bounds": [[west, south], [east, north]],
        },
        "contourPoints": results_lib.contour_points(grid, (west, south, east, north)),
        "contourBounds": [[west, south], [east, north]],
        "warnings": [f"Tile job failed: {job}" for job in outcome.failed_jobs],
    }

    projects.write_result(project_id, payload, image)
    projects.record_run(project)
    logger.info("%s %s finished in %.1fs", project_id, body.analysis, duration)
    return payload


@app.get("/projects/{project_id}/results")
def get_results(project_id: str, analysis: str | None = None) -> dict[str, Any] | None:
    _project_or_404(project_id)
    return projects.latest_result(project_id, analysis)


@app.get("/projects/{project_id}/results/{run_identifier}")
def get_result(project_id: str, run_identifier: str) -> dict[str, Any]:
    _project_or_404(project_id)
    try:
        return projects.read_result(project_id, run_identifier)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No run {run_identifier!r}") from None


@app.get("/projects/{project_id}/results/{run_identifier}/image")
def get_result_image(project_id: str, run_identifier: str) -> FileResponse:
    _project_or_404(project_id)
    path = projects.result_image_path(project_id, run_identifier)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No heatmap for this run.")
    return FileResponse(path, media_type="image/png")
