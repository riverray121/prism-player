"""Show store: one folder per show under data_dir/shows, the unpacked bundle.

A bundle is validated in a temporary folder and renamed over the old show folder,
so a replace is atomic and a rejected upload leaves the existing show untouched.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "prism-show/1"
MANIFEST = "manifest.json"
PROJECT_DIR = "project"
SHOW_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
LIGHT_KEY = re.compile(r"^[0-9a-f]{12}-\d+$")


class BadBundle(ValueError):
    pass


class UnknownShow(KeyError):
    pass


def _require(manifest: dict[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in manifest:
        raise BadBundle(f"manifest missing {key}")
    value = manifest[key]
    if not isinstance(value, kind) or isinstance(value, bool):
        raise BadBundle(f"manifest {key} has the wrong type")
    return value


def validate_dir(folder: Path) -> dict[str, Any]:
    """Check an unpacked bundle folder against the bundle format; return its manifest."""
    manifest_path = folder / MANIFEST
    if not manifest_path.is_file():
        raise BadBundle(f"{MANIFEST} missing")
    try:
        manifest = json.loads(manifest_path.read_text())
    except ValueError as exc:
        raise BadBundle(f"{MANIFEST} is not JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BadBundle(f"{MANIFEST} must be an object")
    if manifest.get("schema") != SCHEMA:
        raise BadBundle(f"schema must be {SCHEMA}")
    _require(manifest, "title", str)
    _require(manifest, "artist", str)
    _require(manifest, "duration_s", (int, float))
    audio = _require(manifest, "audio", str)
    frame_rate = _require(manifest, "frame_rate_hz", (int, float))
    frame_count = _require(manifest, "frame_count", int)
    lights = _require(manifest, "lights", list)
    if frame_rate <= 0 or frame_count <= 0:
        raise BadBundle("frame_rate_hz and frame_count must be positive")
    if not _safe_rel(audio) or not (folder / audio).is_file():
        raise BadBundle(f"audio file {audio!r} missing")
    if not (folder / PROJECT_DIR).is_dir():
        raise BadBundle(f"{PROJECT_DIR}/ missing")
    if not lights:
        raise BadBundle("lights is empty")
    seen: set[str] = set()
    for i, light in enumerate(lights):
        if not isinstance(light, dict):
            raise BadBundle(f"lights[{i}] must be an object")
        key = _require(light, "key", str)
        if not LIGHT_KEY.match(key):
            raise BadBundle(f"lights[{i}] key {key!r} is not <mac>-<output>")
        if key in seen:
            raise BadBundle(f"duplicate light key {key}")
        seen.add(key)
        _require(light, "hub_mac", str)
        _require(light, "output", int)
        pixel_count = _require(light, "pixel_count", int)
        frames = _require(light, "frames", str)
        if pixel_count <= 0:
            raise BadBundle(f"light {key} pixel_count must be positive")
        if not _safe_rel(frames) or not (folder / frames).is_file():
            raise BadBundle(f"light {key} frames file {frames!r} missing")
        expected = frame_count * pixel_count * 3
        actual = (folder / frames).stat().st_size
        if actual != expected:
            raise BadBundle(f"light {key} frames file is {actual} bytes, expected {expected}")
    return manifest


def _safe_rel(rel: str) -> bool:
    parts = Path(rel).parts
    return bool(parts) and not Path(rel).is_absolute() and ".." not in parts


def summary(show_id: str, manifest: dict[str, Any], updated_at: str) -> dict[str, Any]:
    return {
        "id": show_id,
        "title": manifest["title"],
        "artist": manifest["artist"],
        "duration_s": manifest["duration_s"],
        "frame_rate_hz": manifest["frame_rate_hz"],
        "light_count": len(manifest["lights"]),
        "updated_at": updated_at,
        "request_id": manifest.get("request_id"),
    }


class ShowStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "shows"
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, show_id: str) -> Path:
        if not SHOW_ID.match(show_id):
            raise UnknownShow(show_id)
        return self.root / show_id

    def exists(self, show_id: str) -> bool:
        return self.folder(show_id).is_dir()

    def manifest(self, show_id: str) -> dict[str, Any]:
        path = self.folder(show_id) / MANIFEST
        if not path.is_file():
            raise UnknownShow(show_id)
        result: dict[str, Any] = json.loads(path.read_text())
        return result

    def _updated_at(self, show_id: str) -> str:
        mtime = (self.folder(show_id) / MANIFEST).stat().st_mtime
        return datetime.fromtimestamp(mtime, UTC).isoformat().replace("+00:00", "Z")

    def get(self, show_id: str) -> dict[str, Any]:
        return summary(show_id, self.manifest(show_id), self._updated_at(show_id))

    def list(self) -> list[dict[str, Any]]:
        shows = []
        for path in self.root.iterdir():
            if (path / MANIFEST).is_file():
                shows.append(self.get(path.name))
        shows.sort(key=lambda s: s["updated_at"], reverse=True)
        return shows

    def put(self, show_id: str, zip_path: Path) -> dict[str, Any]:
        """Validate a bundle zip and install it as show_id, replacing any existing show."""
        target = self.folder(show_id)
        staging = Path(tempfile.mkdtemp(prefix=f".{show_id}.", dir=self.root))
        try:
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    for member in zf.namelist():
                        if not _safe_rel(member):
                            raise BadBundle(f"unsafe path in zip: {member!r}")
                    zf.extractall(staging)
            except zipfile.BadZipFile as exc:
                raise BadBundle(f"not a zip file: {exc}") from exc
            validate_dir(staging)
            # Touch the manifest so updated_at reflects the install time, not the zip's.
            (staging / MANIFEST).touch()
            if target.is_dir():
                old = Path(tempfile.mkdtemp(prefix=f".{show_id}.old.", dir=self.root))
                old.rmdir()
                target.rename(old)
                staging.rename(target)
                shutil.rmtree(old, ignore_errors=True)
            else:
                staging.rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self.get(show_id)

    def bundle(self, show_id: str, out: Path) -> Path:
        """Re-zip a show folder into out and return it."""
        folder = self.folder(show_id)
        if not folder.is_dir():
            raise UnknownShow(show_id)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(folder).as_posix())
        return out

    def audio_path(self, show_id: str) -> Path:
        return self.folder(show_id) / str(self.manifest(show_id)["audio"])

    def delete(self, show_id: str) -> None:
        folder = self.folder(show_id)
        if not folder.is_dir():
            raise UnknownShow(show_id)
        shutil.rmtree(folder)
