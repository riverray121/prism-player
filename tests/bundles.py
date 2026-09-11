"""Builds small valid show bundles in memory for tests."""

from __future__ import annotations

import io
import json
import struct
import zipfile
from typing import Any

LIGHTS = [("1cc3abbbc85c-0", 4), ("1cc3abbbc85c-1", 3)]
FRAME_COUNT = 10
FRAME_RATE = 40


def manifest(**overrides: Any) -> dict[str, Any]:
    m: dict[str, Any] = {
        "schema": "prism-show/1",
        "title": "Dior",
        "artist": "Joji",
        "duration_s": FRAME_COUNT / FRAME_RATE,
        "audio": "audio.wav",
        "frame_rate_hz": FRAME_RATE,
        "frame_count": FRAME_COUNT,
        "latency_ms": 90,
        "lights": [
            {
                "key": key,
                "hub_mac": key.split("-")[0],
                "output": int(key.split("-")[1]),
                "name": f"Output {i + 1}",
                "pixel_count": count,
                "frames": f"frames/{key}.bin",
            }
            for i, (key, count) in enumerate(LIGHTS)
        ],
        "external": {"spotify_uri": "spotify:track:abc"},
        "prism_version": "0.1.0",
    }
    m.update(overrides)
    return m


def wav_bytes(samples: int = 400) -> bytes:
    data = b"\x00\x00" * samples
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


def frames(pixel_count: int, frame_count: int = FRAME_COUNT) -> bytes:
    return bytes((i % 256) for i in range(frame_count * pixel_count * 3))


def bundle(
    manifest_obj: dict[str, Any] | None = None,
    *,
    drop: set[str] = frozenset(),
    frame_sizes: dict[str, int] | None = None,
) -> bytes:
    m = manifest_obj or manifest()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(m))
        if "audio" not in drop:
            zf.writestr(m["audio"], wav_bytes())
        for light in m["lights"]:
            if light["frames"] in drop:
                continue
            size = (frame_sizes or {}).get(light["key"])
            data = frames(light["pixel_count"]) if size is None else b"\x00" * size
            zf.writestr(light["frames"], data)
        if "project" not in drop:
            zf.writestr("project/profile.json", json.dumps({"timeline": {"frame_rate_hz": 100}}))
            zf.writestr("project/mapping/mapping.json", json.dumps({"programs": [], "patch": {}}))
    return buf.getvalue()
