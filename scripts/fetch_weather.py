"""Fetch reference EPW files listed in weather_data/weather_manifest.yaml.

    python scripts/fetch_weather.py --all
    python scripts/fetch_weather.py dubai_ae

For each entry: download the zip from `source_url`, take the single .epw inside, verify its SHA-256 against the
manifest and only then write `weather_data/<filename>` (git-ignored). A checksum mismatch aborts without writing.
Entries that are not downloadable (the generated `synthetic` entry) are skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "weather_data" / "weather_manifest.yaml"
DEST = ROOT / "weather_data"
USER_AGENT = "microclimate-studio-fetch/0.1"


class FetchError(RuntimeError):
    """Download, archive or checksum problem."""


class ChecksumMismatch(FetchError):
    pass


def http_download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - https URL from manifest
            return response.read()
    except OSError as exc:
        raise FetchError(f"download failed for {url}: {exc}") from exc


def load_entries(manifest: Path = MANIFEST) -> list[dict]:
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return list(data.get("files") or [])


def is_downloadable(entry: dict) -> bool:
    return str(entry.get("source_url", "")).startswith(("https://", "http://"))


def extract_epw(zip_bytes: bytes) -> bytes:
    """Return the bytes of the single .epw in the archive (read in memory; nothing is extracted to disk)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise FetchError("downloaded file is not a zip archive") from exc
    names = [n for n in archive.namelist() if n.lower().endswith(".epw")]
    if len(names) != 1:
        raise FetchError(f"expected exactly one .epw in the archive, found {len(names)}")
    return archive.read(names[0])


def fetch_entry(
    entry: dict,
    dest: Path = DEST,
    download: Callable[[str], bytes] = http_download,
    force: bool = False,
) -> Path:
    """Fetch one manifest entry; returns the written path. Raises ChecksumMismatch on a bad hash."""
    if not is_downloadable(entry):
        raise FetchError(f"{entry.get('id')}: no downloadable source_url")
    expected = str(entry.get("sha256", "")).lower()
    if not expected:
        raise FetchError(f"{entry.get('id')}: manifest has no sha256")
    target = dest / Path(str(entry["filename"])).name
    if target.exists() and not force and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return target
    epw = extract_epw(download(str(entry["source_url"])))
    actual = hashlib.sha256(epw).hexdigest()
    if actual != expected:
        raise ChecksumMismatch(
            f"{entry.get('id')}: sha256 mismatch (expected {expected}, got {actual}) from {entry['source_url']}"
        )
    dest.mkdir(parents=True, exist_ok=True)
    target.write_bytes(epw)
    return target


def main(argv: list[str] | None = None, download: Callable[[str], bytes] = http_download) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", help="manifest ids to fetch")
    parser.add_argument("--all", action="store_true", help="fetch every downloadable entry")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--dest", type=Path, default=DEST)
    parser.add_argument("--force", action="store_true", help="re-download even if a verified file exists")
    args = parser.parse_args(argv)

    entries = load_entries(args.manifest)
    by_id = {str(e.get("id")): e for e in entries}
    if args.all:
        selected = [e for e in entries if is_downloadable(e)]
    elif args.ids:
        unknown = [i for i in args.ids if i not in by_id]
        if unknown:
            print(f"unknown id(s): {', '.join(unknown)}; known: {', '.join(by_id)}", file=sys.stderr)
            return 2
        selected = [by_id[i] for i in args.ids]
    else:
        parser.print_usage(sys.stderr)
        print("give --all or at least one id", file=sys.stderr)
        return 2

    failed = 0
    for entry in selected:
        try:
            path = fetch_entry(entry, args.dest, download, args.force)
            print(f"ok    {entry['id']}: {path}")
        except FetchError as exc:
            failed += 1
            print(f"FAIL  {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
