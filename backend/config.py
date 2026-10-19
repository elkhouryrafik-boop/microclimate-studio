"""Paths and runtime settings for the Microclimate Studio backend."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# The API key lives in the repo-root .env (see README); backend/.env wins if present.
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)

WEATHER_DIR = PROJECT_ROOT / "weather_data"
WEATHER_MANIFEST = WEATHER_DIR / "weather_manifest.yaml"

CACHE_DIR = BACKEND_DIR / "cache"
PROJECTS_DIR = CACHE_DIR / "projects"
CUSTOM_WEATHER_DIR = CACHE_DIR / "weather"

for _d in (CACHE_DIR, PROJECTS_DIR, CUSTOM_WEATHER_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Metres of open ground kept around the building envelope when deriving the
# site polygon. 50 m is roughly two street widths — enough context for wake
# and shadow effects without pushing the polygon past one 512 m tile.
SITE_BUFFER_M = float(os.getenv("MCS_SITE_BUFFER_M", "50"))

# One tile is 512 x 512 m. Staying inside a single tile keeps runs at
# 10-60 s and avoids seam artefacts entirely.
MAX_SITE_SPAN_M = float(os.getenv("MCS_MAX_SITE_SPAN_M", "512"))

# Upper bound on triangles sent per building. Revit exports carry interior
# detail the microclimate models do not use; past this we decimate.
MAX_TRIANGLES_PER_BUILDING = int(os.getenv("MCS_MAX_TRIANGLES", "200000"))

ALLOWED_ORIGINS = os.getenv(
    "MCS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
).split(",")


def api_key() -> str | None:
    return os.getenv("INFRARED_API_KEY") or None


def api_key_configured() -> bool:
    key = api_key()
    return bool(key) and key != "your_api_key_here"


def engine() -> str:
    """Active analysis engine: "fake" (synthetic, offline) or "infrared" (real SDK).

    `MCS_ENGINE` wins when it is one of the two values; otherwise the engine is
    "infrared" if an API key is configured and "fake" if not.
    """
    choice = (os.getenv("MCS_ENGINE") or "").strip().lower()
    if choice in ("fake", "infrared"):
        return choice
    return "infrared" if api_key_configured() else "fake"
