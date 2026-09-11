"""Offset calibration: a click show (a click in the audio and a white flash on
every hub output once a second) played through the configured backend while the
offset is nudged from the terminal until flash and click coincide."""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import struct
import sys
import tempfile
import termios
import tty
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from prism_player import config
from prism_player.audio.base import AudioBackend
from prism_player.ddp import Sender
from prism_player.engine import Engine
from prism_player.hooks import Hooks
from prism_player.hubs import Hubs
from prism_player.store import ShowStore

SHOW_ID = "calibrate-click"
SAMPLE_RATE = 48_000
FRAME_RATE = 40
CLICK_HZ = 1_000.0
CLICK_S = 0.004
# How long discovery gets to find hubs before the click show is built.
DISCOVERY_S = 3.0
KEYS = "+ / - nudge 10 ms, ] / [ nudge 1 ms, r restart, q quit"


def click_wav(path: Path, seconds: float, interval: float) -> int:
    """Write a mono 16-bit wav with a short 1 kHz burst every interval; returns the sample count."""
    total = int(seconds * SAMPLE_RATE)
    burst = int(CLICK_S * SAMPLE_RATE)
    step = int(interval * SAMPLE_RATE)
    samples = bytearray(total * 2)
    for start in range(0, total, step):
        for n in range(min(burst, total - start)):
            value = int(0.8 * 32767 * math.sin(2 * math.pi * CLICK_HZ * n / SAMPLE_RATE))
            struct.pack_into("<h", samples, (start + n) * 2, value)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(samples))
    return total


def click_frames(pixel_count: int, seconds: float, interval: float, lit_frames: int = 3) -> bytes:
    """Frame-major RGB: full white for lit_frames at every click, black otherwise."""
    frame_count = int(seconds * FRAME_RATE)
    step = int(round(interval * FRAME_RATE))
    frame = pixel_count * 3
    data = bytearray(frame_count * frame)
    for start in range(0, frame_count, step):
        for i in range(start, min(start + lit_frames, frame_count)):
            data[i * frame : (i + 1) * frame] = b"\xff" * frame
    return bytes(data)


def click_show(
    folder: Path,
    lights: list[tuple[str, int]],
    seconds: float = 30.0,
    interval: float = 1.0,
) -> dict[str, Any]:
    """Write a click show bundle folder and return its manifest."""
    (folder / "frames").mkdir(parents=True, exist_ok=True)
    (folder / "project").mkdir(exist_ok=True)
    (folder / "project" / "calibrate.txt").write_text("generated click show\n")
    click_wav(folder / "audio.wav", seconds, interval)
    manifest: dict[str, Any] = {
        "schema": "prism-show/1",
        "title": "Calibration click",
        "artist": "prism-player",
        "duration_s": seconds,
        "audio": "audio.wav",
        "frame_rate_hz": FRAME_RATE,
        "frame_count": int(seconds * FRAME_RATE),
        "latency_ms": 0,
        "lights": [],
        "external": {},
        "prism_version": "",
    }
    for key, count in lights:
        (folder / "frames" / f"{key}.bin").write_bytes(click_frames(count, seconds, interval))
        mac, _, output = key.rpartition("-")
        manifest["lights"].append(
            {
                "key": key,
                "hub_mac": mac,
                "output": int(output),
                "name": key,
                "pixel_count": count,
                "frames": f"frames/{key}.bin",
            }
        )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


async def _read_keys(queue: asyncio.Queue[str]) -> None:
    loop = asyncio.get_running_loop()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        while True:
            key = await loop.run_in_executor(None, sys.stdin.read, 1)
            await queue.put(key)
            if key == "q":
                return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


async def run(
    cfg: config.Config,
    backend_for: Callable[[config.Config, aiohttp.ClientSession], AudioBackend],
) -> None:
    shows = ShowStore(cfg.data_dir)
    async with aiohttp.ClientSession() as session:
        hubs = Hubs(session, cfg.hubs)
        await hubs.start()
        print(f"finding hubs ({DISCOVERY_S:.0f} s)...")
        await asyncio.sleep(DISCOVERY_S)
        lights: list[tuple[str, int]] = []
        for mac in sorted(set(hubs.configured) | set(hubs.discovered)):
            hub = await hubs.resolve(mac)
            if hub is None:
                print(f"hub {mac}: unreachable, skipped")
                continue
            for i, out in enumerate(hub.outputs):
                lights.append((f"{mac}-{i}", out.count))
        if not lights:
            print("no hub outputs found; list hubs in the config or check mDNS")
            await hubs.stop()
            return
        print(f"{len(lights)} outputs: " + ", ".join(k for k, _ in lights))

        tmp = Path(tempfile.mkdtemp(prefix="prism-calibrate-"))
        try:
            click_show(tmp / "show", lights)
            zip_path = Path(shutil.make_archive(str(tmp / "show"), "zip", tmp / "show"))
            shows.put(SHOW_ID, zip_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        sender = Sender()
        engine = Engine(
            shows,
            hubs,
            sender,
            backend_for(cfg, session),
            Hooks(session),
            audio_url=lambda show_id: f"{cfg.audio.audio_url_base}/v1/shows/{show_id}/audio",
            offset_ms=cfg.audio.offset_ms,
        )
        offset = cfg.audio.offset_ms
        keys: asyncio.Queue[str] = asyncio.Queue()
        reader = asyncio.create_task(_read_keys(keys))
        try:
            print(f"offset {offset} ms. {KEYS}")
            await engine.play([SHOW_ID])
            while True:
                key = await keys.get()
                if key == "q":
                    break
                if key == "r":
                    await engine.play([SHOW_ID])
                    continue
                delta = {"+": 10, "-": -10, "]": 1, "[": -1}.get(key)
                if delta is None:
                    continue
                offset += delta
                engine.set_offset(offset)
                print(f"offset {offset} ms", end="\r", flush=True)
                if engine.current is None:
                    await engine.play([SHOW_ID])
        finally:
            reader.cancel()
            await engine.stop()
            sender.close()
            await hubs.stop()
            if shows.exists(SHOW_ID):
                shows.delete(SHOW_ID)
        print(f"\naudio.offset_ms: {offset}")
