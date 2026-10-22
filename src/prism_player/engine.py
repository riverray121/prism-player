"""Playback: one show at a time from one clock, lights over DDP, audio through a backend.

Play sequence: resolve the show's lights onto hubs, read each hub's power state, power
hubs on, start audio, start the clock, send frames on the bundle's rate until the last,
then restore. Restore stops sending, blacks out and powers off hubs that were off, and
leaves hubs that were on to WLED's realtime timeout.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from prism_player.audio.base import AudioBackend
from prism_player.ddp import blackout_packets, frame_packets
from prism_player.hooks import Hooks
from prism_player.hubs import HubDirectory, Target, parse_key
from prism_player.store import ShowStore, UnknownShow

log = logging.getLogger(__name__)

POSITION_POLL_S = 2.0
# Consecutive polls disagreeing by more than a frame before the clock re-bases.
POSITION_STRIKES = 2


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FrameSender(Protocol):
    def send(self, address: str, packets: list[bytes]) -> None: ...


@dataclass
class HubRun:
    address: str
    was_on: bool
    lights: list[tuple[Target, bytes]] = field(default_factory=list)


@dataclass
class Current:
    show_id: str
    summary: dict[str, Any]
    frame_rate_hz: float
    frame_count: int
    t0: float | None = None
    skipped_lights: list[str] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        shows: ShowStore,
        hubs: HubDirectory,
        sender: FrameSender,
        audio: AudioBackend,
        hooks: Hooks,
        *,
        audio_url: Callable[[str], str],
        offset_ms: int = 0,
        on_play_url: str | None = None,
        on_stop_url: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.shows = shows
        self.hubs = hubs
        self.sender = sender
        self.audio = audio
        self.hooks = hooks
        self.audio_url = audio_url
        self.offset_s = offset_ms / 1000
        self.on_play_url = on_play_url
        self.on_stop_url = on_stop_url
        self.clock: Clock = clock or MonotonicClock()
        self.queue: list[str] = []
        self.current: Current | None = None
        self._runner: asyncio.Task[None] | None = None
        self._show_task: asyncio.Task[None] | None = None
        self._started: asyncio.Event = asyncio.Event()

    # ── control ──────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        cur = self.current
        position = None
        if cur is not None and cur.t0 is not None:
            position = max(0.0, self.clock.now() - cur.t0)
        return {
            "state": "playing" if cur is not None else "idle",
            "show": cur.summary if cur is not None else None,
            "position_s": position,
            "queue": list(self.queue),
            "skipped_lights": list(cur.skipped_lights) if cur is not None else [],
        }

    async def play(self, show_ids: list[str]) -> None:
        for show_id in show_ids:
            if not self.shows.exists(show_id):
                raise UnknownShow(show_id)
        if not show_ids:
            raise ValueError("nothing to play")
        await self.stop()
        self.queue = list(show_ids)
        self._started = asyncio.Event()
        self._runner = asyncio.create_task(self._run_queue())
        # Return once the first show is current, so a status read right after
        # play reports it.
        await self._started.wait()

    def set_offset(self, offset_ms: int) -> None:
        """Change the light delay live: the current show's clock shifts with it."""
        new = offset_ms / 1000
        if self.current is not None and self.current.t0 is not None:
            self.current.t0 += new - self.offset_s
        self.offset_s = new

    async def play_all(self, shuffle: bool = False) -> None:
        ids = [s["id"] for s in self.shows.list()]
        if shuffle:
            random.shuffle(ids)
        await self.play(ids)

    async def stop(self) -> None:
        self.queue = []
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
            return
        # Nothing of ours is running, but the speaker may still be: a show cut
        # short by a process restart leaves the audio stream playing. A stop
        # request means silence either way.
        await self.audio.stop()

    def announce_startup(self) -> None:
        """Tell the hooks' listeners that no show is playing. A restart mid-show
        never reached the stop hook, so the listener's flag would stay set."""
        self.hooks.fire(self.on_stop_url, "stop", {"id": None, "reason": "startup"})

    async def next(self) -> None:
        task = self._show_task
        if task is None:
            return
        self._started = asyncio.Event()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Returns once the next queued show is current, or the queue has ended.
        await self._started.wait()

    # ── playback ─────────────────────────────────────────────────────────

    async def _run_queue(self) -> None:
        try:
            while self.queue:
                show_id = self.queue.pop(0)
                self._show_task = asyncio.create_task(self._play_one(show_id))
                try:
                    await self._show_task
                except asyncio.CancelledError:
                    # next() cancels only the show task; stop() cancels this
                    # runner too, and that cancellation must propagate.
                    if self._runner is None:
                        raise
                finally:
                    self._show_task = None
        finally:
            self._runner = None
            self._started.set()

    async def _play_one(self, show_id: str) -> None:
        manifest = self.shows.manifest(show_id)
        folder = self.shows.folder(show_id)
        cur = Current(
            show_id=show_id,
            summary=self.shows.get(show_id),
            frame_rate_hz=float(manifest["frame_rate_hz"]),
            frame_count=int(manifest["frame_count"]),
        )
        self.current = cur
        self._started.set()
        runs: dict[str, HubRun] = {}
        try:
            runs = await self._resolve(manifest["lights"], folder, cur)
            for run in runs.values():
                if not run.was_on:
                    await self.hubs.set_power(run.address, True)
            self.hooks.fire(self.on_play_url, "play", cur.summary)
            await self.audio.start(self.audio_url(show_id))
            cur.t0 = self.clock.now() + self.offset_s
            await self._stream(cur, list(runs.values()))
        finally:
            await self._restore(runs)
            await self.audio.stop()
            self.hooks.fire(self.on_stop_url, "stop", cur.summary)
            self.current = None

    async def _resolve(
        self, lights: list[dict[str, Any]], folder: Path, cur: Current
    ) -> dict[str, HubRun]:
        runs: dict[str, HubRun] = {}
        hubs_by_mac: dict[str, Any] = {}
        for light in lights:
            key = str(light["key"])
            mac, output = parse_key(key)
            if mac not in hubs_by_mac:
                hubs_by_mac[mac] = await self.hubs.resolve(mac)
            hub = hubs_by_mac[mac]
            if hub is None or output >= len(hub.outputs):
                cur.skipped_lights.append(key)
                continue
            out = hub.outputs[output]
            target = Target(key, hub.address, out.start, int(light["pixel_count"]))
            if hub.address not in runs:
                runs[hub.address] = HubRun(hub.address, was_on=await self.hubs.is_on(hub.address))
            data = (folder / str(light["frames"])).read_bytes()
            runs[hub.address].lights.append((target, data))
        if not runs:
            log.warning("show %s: no light resolved to a hub", cur.show_id)
        return runs

    async def _stream(self, cur: Current, runs: list[HubRun]) -> None:
        assert cur.t0 is not None
        period = 1.0 / cur.frame_rate_hz
        i = 0
        next_poll = self.clock.now() + POSITION_POLL_S
        strikes = 0
        while i < cur.frame_count:
            deadline = cur.t0 + i * period
            now = self.clock.now()
            if now < deadline:
                await self.clock.sleep(deadline - now)
                now = self.clock.now()
            # Late by a whole frame or more: skip to the frame due now.
            due = int((now - cur.t0) / period)
            if due > i:
                i = min(due, cur.frame_count - 1)
            for run in runs:
                for target, data in run.lights:
                    size = target.pixel_count * 3
                    frame = memoryview(data)[i * size : (i + 1) * size]
                    self.sender.send(run.address, frame_packets(frame, target.start * 3))
            i += 1
            if now >= next_poll:
                next_poll = now + POSITION_POLL_S
                pos = await self.audio.position()
                if pos is not None:
                    # Lights run offset_s behind the audio: light time is
                    # now - t0, audio time is that plus the offset.
                    expected = self.clock.now() - cur.t0 + self.offset_s
                    if abs(pos - expected) > period:
                        strikes += 1
                        if strikes >= POSITION_STRIKES:
                            cur.t0 = self.clock.now() - pos + self.offset_s
                            strikes = 0
                    else:
                        strikes = 0

    async def _restore(self, runs: dict[str, HubRun]) -> None:
        for run in runs.values():
            if run.was_on:
                continue
            try:
                for target, _ in run.lights:
                    self.sender.send(
                        run.address, blackout_packets(target.pixel_count, target.start * 3)
                    )
                await self.hubs.set_power(run.address, False)
            except Exception as exc:
                log.warning("restore of hub %s failed: %s", run.address, exc)
