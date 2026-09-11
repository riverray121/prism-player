from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from prism_player.api import build_app
from prism_player.config import Config
from prism_player.hooks import Hooks
from prism_player.requests import RequestStore
from prism_player.store import ShowStore

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
        app = build_app(cfg, "secret", shows, requests, hooks)
        async with TestClient(TestServer(app)) as tc:
            tc.shows = shows
            tc.hooks = hooks
            yield tc
        requests.close()
