"""HaBackend against a fake Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from prism_player.audio import ha
from prism_player.audio.ha import HaBackend, position_from_state

ENTITY = "media_player.living_room_speaker"


class FakeHa:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.state = "idle"
        self.attributes: dict = {}
        self.app = web.Application()
        self.app.router.add_post("/api/services/media_player/{service}", self.service)
        self.app.router.add_get("/api/states/{entity}", self.states)

    async def service(self, request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer hatok"
        self.calls.append((request.match_info["service"], await request.json()))
        return web.json_response([])

    async def states(self, request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer hatok"
        return web.json_response(
            {
                "entity_id": request.match_info["entity"],
                "state": self.state,
                "attributes": self.attributes,
            }
        )


@pytest.fixture
async def fake():
    fake = FakeHa()
    async with TestServer(fake.app) as server, aiohttp.ClientSession() as session:
        backend = HaBackend(session, f"http://{server.host}:{server.port}", "hatok", ENTITY)
        yield fake, backend


async def test_start_calls_play_media_and_waits_for_playing(fake, monkeypatch):
    fake_ha, backend = fake
    monkeypatch.setattr(ha, "START_POLL_S", 0.01)

    async def flip() -> None:
        await asyncio.sleep(0.03)
        fake_ha.state = "playing"

    asyncio.create_task(flip())
    await backend.start("http://player/v1/shows/s/audio")
    assert fake_ha.calls == [
        (
            "play_media",
            {
                "entity_id": ENTITY,
                "media_content_id": "http://player/v1/shows/s/audio",
                "media_content_type": "music",
            },
        )
    ]


async def test_start_raises_when_playback_never_starts(fake, monkeypatch):
    _, backend = fake
    monkeypatch.setattr(ha, "START_POLL_S", 0.01)
    monkeypatch.setattr(ha, "START_TIMEOUT_S", 0.05)
    with pytest.raises(TimeoutError):
        await backend.start("http://player/audio")


async def test_position_from_media_position_and_updated_at(fake):
    fake_ha, backend = fake
    fake_ha.state = "playing"
    fake_ha.attributes = {
        "media_position": 12.0,
        "media_position_updated_at": (datetime.now(UTC) - timedelta(seconds=1.5)).isoformat(),
    }
    pos = await backend.position()
    assert pos == pytest.approx(13.5, abs=0.1)


async def test_position_is_cached_within_a_second(fake):
    fake_ha, backend = fake
    fake_ha.state = "playing"
    fake_ha.attributes = {
        "media_position": 5.0,
        "media_position_updated_at": datetime.now(UTC).isoformat(),
    }
    await backend.position()
    fake_ha.attributes["media_position"] = 50.0
    pos = await backend.position()
    assert pos == pytest.approx(5.0, abs=0.1)


async def test_position_none_while_paused_or_without_attributes(fake):
    fake_ha, backend = fake
    fake_ha.state = "paused"
    fake_ha.attributes = {"media_position": 1.0}
    assert await backend.position() is None
    now = datetime.now(UTC)
    assert position_from_state({"state": "playing", "attributes": {}}, now) is None
    assert position_from_state(None, now) is None
    assert (
        position_from_state(
            {
                "state": "playing",
                "attributes": {"media_position": 2.0, "media_position_updated_at": "bad"},
            },
            now,
        )
        is None
    )


async def test_stop_calls_media_stop(fake):
    fake_ha, backend = fake
    await backend.stop()
    assert fake_ha.calls == [("media_stop", {"entity_id": ENTITY})]
