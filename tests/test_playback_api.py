from __future__ import annotations

import asyncio

from tests.bundles import bundle
from tests.conftest import AUTH

ZIP = {"Content-Type": "application/zip", **AUTH}
MAC = "1cc3abbbc85c"


async def wait_idle(engine) -> None:
    for _ in range(10_000):
        if engine.current is None and engine._runner is None:
            return
        await asyncio.sleep(0)
    raise AssertionError("engine did not go idle")


async def test_status_idle_and_auth(client):
    assert (await client.get("/v1/status")).status == 401
    resp = await client.get("/v1/status", headers=AUTH)
    assert await resp.json() == {
        "state": "idle",
        "show": None,
        "position_s": None,
        "queue": [],
        "skipped_lights": [],
    }


async def test_play_stop_next_and_status(client):
    client.hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=False)
    for show_id in ("a", "b"):
        assert (await client.put(f"/v1/shows/{show_id}", data=bundle(), headers=ZIP)).status == 200

    client.clock.pause()
    resp = await client.post("/v1/play", json={"queue": ["a", "b"]}, headers=AUTH)
    assert resp.status == 200
    body = await resp.json()
    assert body["state"] == "playing" and body["show"]["id"] == "a"
    assert body["queue"] == ["b"]

    resp = await client.post("/v1/next", headers=AUTH)
    body = await resp.json()
    assert body["state"] == "playing" and body["show"]["id"] == "b"
    assert body["queue"] == []

    resp = await client.post("/v1/stop", headers=AUTH)
    assert (await resp.json())["state"] == "idle"
    assert client.hubs.power_calls[-1] == ("10.0.0.5", False)


async def test_play_all_and_bad_bodies(client):
    client.hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=True)
    assert (await client.put("/v1/shows/a", data=bundle(), headers=ZIP)).status == 200
    resp = await client.post("/v1/play", json={"queue": "all", "shuffle": True}, headers=AUTH)
    assert resp.status == 200
    await wait_idle(client.engine)
    assert (await client.post("/v1/play", json={}, headers=AUTH)).status == 400
    assert (await client.post("/v1/play", json={"show": "nope"}, headers=AUTH)).status == 404
    assert (await client.get("/v1/status", headers=AUTH)).status == 200
