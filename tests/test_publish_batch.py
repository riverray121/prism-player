from __future__ import annotations

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from prism_player.hooks import Hooks
from prism_player.publish_batch import MAX_HOLD_S, PublishBatcher


async def test_batches_until_nothing_is_pending_and_releases_stale_batches():
    received: list[dict] = []

    async def take(request: web.Request) -> web.Response:
        received.append(await request.json())
        return web.Response()

    app = web.Application()
    app.router.add_post("/hook", take)
    pending = {"n": 2}
    now = {"t": 1000.0}
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            hooks = Hooks(session)
            b = PublishBatcher(
                hooks,
                f"http://{server.host}:{server.port}/hook",
                lambda: pending["n"],
                clock=lambda: now["t"],
            )
            b.add({"id": "a", "title": "A"})
            b.add({"id": "b", "title": "B"})
            b.add({"id": "a", "title": "A again"})
            await hooks.drain()
            assert received == []
            pending["n"] = 0
            b.check()
            await hooks.drain()
            assert len(received) == 1
            assert received[0]["count"] == 2
            assert [s["title"] for s in received[0]["shows"]] == ["B", "A again"]
            # A stuck request must not hold a later batch forever.
            pending["n"] = 1
            b.add({"id": "c", "title": "C"})
            now["t"] += MAX_HOLD_S
            b.check()
            await hooks.drain()
            assert len(received) == 2 and received[1]["pending"] == 1
            # No url configured: nothing is held or sent.
            quiet = PublishBatcher(hooks, None, lambda: 0)
            quiet.add({"id": "z"})
            assert quiet.held == []
