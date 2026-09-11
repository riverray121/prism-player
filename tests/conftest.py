from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from prism_player.api import build_app
from prism_player.audio.none import NoneAudio
from prism_player.config import Config
from prism_player.engine import Engine
from prism_player.hooks import Hooks
from prism_player.requests import RequestStore
from prism_player.store import ShowStore
from tests.fakes import FakeClock, FakeHubs, FakeSender

AUTH = {"Authorization": "Bearer secret"}


@pytest.fixture
async def hook_target():
    """A local server that records every POST it receives."""
    received: list[dict] = []

    async def take(request: web.Request) -> web.Response:
        received.append(await request.json())
        return web.Response()

    app = web.Application()
    app.router.add_post("/hook", take)
    async with TestServer(app) as server:
        yield f"http://{server.host}:{server.port}/hook", received


@pytest.fixture
async def client(tmp_path, hook_target):
    url, _ = hook_target
    cfg = Config(data_dir=tmp_path)
    cfg.hooks.on_request = url
    shows = ShowStore(tmp_path)
    requests = RequestStore(tmp_path / "requests.sqlite")
    async with aiohttp.ClientSession() as session:
        hooks = Hooks(session)
        clock = FakeClock()
        hubs = FakeHubs()
        sender = FakeSender(clock)
        engine = Engine(
            shows,
            hubs,
            sender,
            NoneAudio(),
            hooks,
            audio_url=lambda show_id: f"http://player/v1/shows/{show_id}/audio",
            clock=clock,
        )
        app = build_app(cfg, "secret", shows, requests, hooks, engine)
        async with TestClient(TestServer(app)) as tc:
            tc.shows = shows
            tc.hooks = hooks
            tc.engine = engine
            tc.hubs = hubs
            tc.sender = sender
            tc.clock = clock
            yield tc
        await engine.stop()
        requests.close()
