from __future__ import annotations

import asyncio

from tests.conftest import AUTH


async def wait_for(received: list, count: int) -> None:
    for _ in range(50):
        if len(received) >= count:
            return
        await asyncio.sleep(0.02)


async def test_create_dedupe_patch_list(client, hook_target):
    _, received = hook_target
    body = {"title": "Dior", "artist": "Joji", "external": {"spotify_uri": "spotify:track:abc"}}
    resp = await client.post("/v1/requests", json=body, headers=AUTH)
    assert resp.status == 201
    first = await resp.json()
    assert first["status"] == "open" and first["show_id"] is None
    assert first["requested_at"].endswith("Z")

    resp = await client.post("/v1/requests", json=body, headers=AUTH)
    assert resp.status == 200
    assert (await resp.json())["id"] == first["id"]

    resp = await client.post(
        "/v1/requests", json={"title": "Glimpse of Us", "artist": "Joji"}, headers=AUTH
    )
    assert resp.status == 201
    second = await resp.json()

    listed = (await (await client.get("/v1/requests", headers=AUTH)).json())["requests"]
    assert [r["id"] for r in listed] == [second["id"], first["id"]]

    resp = await client.patch(
        f"/v1/requests/{first['id']}",
        json={"status": "published", "show_id": "song-1"},
        headers=AUTH,
    )
    assert resp.status == 200
    updated = await resp.json()
    assert updated["status"] == "published" and updated["show_id"] == "song-1"

    resp = await client.patch(f"/v1/requests/{first['id']}", json={"status": "weird"}, headers=AUTH)
    assert resp.status == 400
    resp = await client.patch("/v1/requests/nope", json={"status": "open"}, headers=AUTH)
    assert resp.status == 404

    await client.hooks.drain()
    await wait_for(received, 2)
    assert len(received) == 2
    assert received[0]["event"] == "request" and received[0]["id"] == first["id"]
    assert received[1]["id"] == second["id"]


async def test_bad_request_body(client):
    resp = await client.post("/v1/requests", json={"title": "x"}, headers=AUTH)
    assert resp.status == 400
    resp = await client.post(
        "/v1/requests", json={"title": "x", "artist": "y", "external": "no"}, headers=AUTH
    )
    assert resp.status == 400
