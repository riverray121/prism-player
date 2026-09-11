from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from prism_player.audio.none import NoneAudio
from prism_player.engine import Engine
from prism_player.hooks import Hooks
from prism_player.store import ShowStore, UnknownShow
from tests.bundles import FRAME_COUNT, FRAME_RATE, LIGHTS, bundle, manifest
from tests.fakes import FakeClock, FakeHubs, FakeSender

MAC = "1cc3abbbc85c"
PERIOD = 1 / FRAME_RATE


def install(shows: ShowStore, show_id: str, data: bytes | None = None) -> None:
    path = shows.root / f"{show_id}.upload.zip"
    path.write_bytes(data or bundle())
    shows.put(show_id, path)
    path.unlink()


@pytest.fixture
async def rig(tmp_path: Path):
    shows = ShowStore(tmp_path)
    install(shows, "a")
    install(shows, "b")
    clock = FakeClock()
    hubs = FakeHubs()
    hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=False)
    sender = FakeSender(clock)
    async with aiohttp.ClientSession() as session:
        hooks = Hooks(session)
        engine = Engine(
            shows,
            hubs,
            sender,
            NoneAudio(),
            hooks,
            audio_url=lambda i: f"http://p/{i}",
            clock=clock,
        )
        yield engine, shows, hubs, sender, clock, hooks
        await engine.stop()


async def wait_idle(engine: Engine) -> None:
    for _ in range(10_000):
        if engine.current is None and engine._runner is None:
            return
        await asyncio.sleep(0)
    raise AssertionError("engine did not go idle")


def frames_for(sender: FakeSender, light_index: int) -> list:
    start = LIGHTS[light_index][1] and [0, 4][light_index]
    return [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == start * 3]


async def test_frames_go_out_on_the_bundle_rate(rig):
    engine, shows, hubs, sender, clock, _ = rig
    await engine.play(["a"])
    await wait_idle(engine)
    light0 = [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == 0]
    # FRAME_COUNT frames plus the blackout at restore, all to the hub address.
    assert len(light0) == FRAME_COUNT + 1
    assert all(s.address == "10.0.0.5" for s in sender.sent)
    times = [s.t for s in light0[:FRAME_COUNT]]
    assert times == pytest.approx([i * PERIOD for i in range(FRAME_COUNT)])
    # Frame i carries the bytes at i * pixel_count * 3 of the light's frame file.
    frame3 = light0[3].packets[0][10:]
    assert frame3 == bytes(((3 * 4 * 3) + j) % 256 for j in range(12))
    # The second light's frames land at its output start (4 px) times 3.
    light1 = [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == 12]
    assert len(light1) == FRAME_COUNT + 1


async def test_late_frames_are_skipped_not_queued(rig):
    engine, shows, hubs, sender, clock, _ = rig
    clock.late_by = 2.5 * PERIOD
    await engine.play(["a"])
    await wait_idle(engine)
    light0 = [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == 0]
    sent_frames = [s.packets[0][10] for s in light0[:-1]]
    # Every sleep overshoots by 2.5 frames, so the scheduler jumps ahead and
    # never sends the frames that were due in between.
    assert len(sent_frames) < FRAME_COUNT
    assert sent_frames == sorted(set(sent_frames))
    assert light0[-1].packets[0][10:] == bytes(12)


async def test_restore_hub_that_was_off(rig):
    engine, shows, hubs, sender, clock, _ = rig
    await engine.play(["a"])
    await wait_idle(engine)
    assert hubs.power_calls == [("10.0.0.5", True), ("10.0.0.5", False)]
    # The blackout comes after the last frame and before the power write.
    last = sender.sent[-1].packets[0]
    assert not any(last[10:])


async def test_hub_that_was_on_gets_no_power_write_and_no_blackout(rig):
    engine, shows, hubs, sender, clock, _ = rig
    hubs.on["10.0.0.5"] = True
    await engine.play(["a"])
    await wait_idle(engine)
    assert hubs.power_calls == []
    assert all(any(s.packets[0][10:]) for s in sender.sent)
    assert hubs.on["10.0.0.5"] is True


async def test_stop_mid_show_restores(rig):
    engine, shows, hubs, sender, clock, _ = rig
    clock.pause()
    await engine.play(["a", "b"])
    for _ in range(5):
        await asyncio.sleep(0)
    assert engine.status()["state"] == "playing"
    await engine.stop()
    assert engine.status()["state"] == "idle"
    assert engine.status()["queue"] == []
    assert hubs.power_calls[-1] == ("10.0.0.5", False)
    assert not any(sender.sent[-1].packets[0][10:])
    sent_light0 = [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == 0]
    assert len(sent_light0) < FRAME_COUNT + 1


async def test_queue_plays_both_with_restore_between(rig):
    engine, shows, hubs, sender, clock, _ = rig
    await engine.play(["a", "b"])
    await wait_idle(engine)
    assert hubs.power_calls == [
        ("10.0.0.5", True),
        ("10.0.0.5", False),
        ("10.0.0.5", True),
        ("10.0.0.5", False),
    ]
    light0 = [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == 0]
    assert len(light0) == 2 * (FRAME_COUNT + 1)


async def test_next_ends_current_and_starts_next(rig):
    engine, shows, hubs, sender, clock, _ = rig
    clock.pause()
    await engine.play(["a", "b"])
    assert engine.status()["show"]["id"] == "a"
    await engine.next()
    for _ in range(20):
        await asyncio.sleep(0)
    assert engine.status()["state"] == "playing"
    assert engine.status()["show"]["id"] == "b"
    clock.resume()
    await wait_idle(engine)
    assert hubs.power_calls.count(("10.0.0.5", False)) == 2


async def test_unresolvable_light_is_skipped_and_reported(rig):
    engine, shows, hubs, sender, clock, _ = rig
    m = manifest()
    m["lights"][1]["key"] = "aaaaaaaaaaaa-0"
    m["lights"][1]["hub_mac"] = "aaaaaaaaaaaa"
    m["lights"][1]["frames"] = "frames/aaaaaaaaaaaa-0.bin"
    install(shows, "c", bundle(m))
    seen: list[dict] = []
    orig = engine._stream

    async def spy(cur, runs):
        seen.append(engine.status())
        await orig(cur, runs)

    engine._stream = spy  # type: ignore[method-assign]
    await engine.play(["c"])
    await wait_idle(engine)
    assert seen[0]["skipped_lights"] == ["aaaaaaaaaaaa-0"]
    assert all(s.address == "10.0.0.5" for s in sender.sent)


async def test_play_unknown_show_raises(rig):
    engine, *_ = rig
    with pytest.raises(UnknownShow):
        await engine.play(["nope"])
    with pytest.raises(ValueError):
        await engine.play([])


async def test_position_correction_rebases_after_two_strikes(tmp_path: Path):
    shows = ShowStore(tmp_path)
    m = manifest(frame_count=400, duration_s=10.0)
    buf = io.BytesIO(bundle(m))
    data = buf.getvalue()
    # Frame files must match the larger frame count.
    with zipfile.ZipFile(io.BytesIO(data)) as zf, zipfile.ZipFile(tmp_path / "big.zip", "w") as out:
        for name in zf.namelist():
            if name.startswith("frames/"):
                key = name[len("frames/") : -4]
                count = dict(LIGHTS)[key]
                out.writestr(name, bytes(400 * count * 3))
            else:
                out.writestr(name, zf.read(name))
    shows.put("long", tmp_path / "big.zip")
    clock = FakeClock()
    hubs = FakeHubs()
    hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=True)
    sender = FakeSender(clock)

    class LaggingAudio(NoneAudio):
        async def position(self) -> float | None:
            # Audio reports it is a full second behind the engine's clock.
            return clock.now() - 1.0

    async with aiohttp.ClientSession() as session:
        engine = Engine(
            shows,
            hubs,
            sender,
            LaggingAudio(),
            Hooks(session),
            audio_url=lambda i: i,
            clock=clock,
        )
        await engine.play(["long"])
        await wait_idle(engine)
    # Two polls (at 2 s and 4 s) disagree by a second, so the clock re-bases a
    # second later at the second poll; frames are never resent, every later
    # frame just lands a second later than its original deadline.
    light0 = [s for s in sender.sent if int.from_bytes(s.packets[0][4:8], "big") == 0]
    assert len(light0) == 400
    assert light0[79].t == pytest.approx(79 * PERIOD)
    assert light0[-1].t == pytest.approx(399 * PERIOD + 1.0)


async def test_hooks_fire_once_per_start_and_end_and_failures_are_ignored(tmp_path: Path):
    received: list[dict] = []

    async def take(request: web.Request) -> web.Response:
        received.append(await request.json())
        return web.Response()

    app = web.Application()
    app.router.add_post("/hook", take)
    async with TestServer(app) as server:
        url = f"http://{server.host}:{server.port}/hook"
        shows = ShowStore(tmp_path)
        install(shows, "a")
        clock = FakeClock()
        hubs = FakeHubs()
        hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=False)
        async with aiohttp.ClientSession() as session:
            hooks = Hooks(session)
            engine = Engine(
                shows,
                hubs,
                FakeSender(clock),
                NoneAudio(),
                hooks,
                audio_url=lambda i: i,
                on_play_url=url,
                on_stop_url="http://127.0.0.1:1/nowhere",
                clock=clock,
            )
            await engine.play(["a"])
            await wait_idle(engine)
            await hooks.drain()
    assert [r["event"] for r in received] == ["play"]
    assert received[0]["id"] == "a" and received[0]["title"] == "Dior"
