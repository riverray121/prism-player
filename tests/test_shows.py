from __future__ import annotations

import io
import json
import zipfile

from tests.bundles import LIGHTS, bundle, manifest
from tests.conftest import AUTH

ZIP = {"Content-Type": "application/zip", **AUTH}


async def test_auth_required_except_healthz(client):
    assert (await client.get("/healthz")).status == 200
    assert (await client.get("/v1/info")).status == 401
    assert (await client.get("/v1/info", headers={"Authorization": "Bearer nope"})).status == 401
    resp = await client.get("/v1/info", headers=AUTH)
    assert resp.status == 200
    body = await resp.json()
    assert body["name"] == "prism-player" and body["api"] == 1


async def test_show_round_trip(client):
    resp = await client.put("/v1/shows/song-1", data=bundle(), headers=ZIP)
    assert resp.status == 200, await resp.text()
    summary = await resp.json()
    assert summary["id"] == "song-1"
    assert summary["title"] == "Dior" and summary["artist"] == "Joji"
    assert summary["light_count"] == 2 and summary["frame_rate_hz"] == 40
    assert summary["updated_at"].endswith("Z")

    listed = await (await client.get("/v1/shows", headers=AUTH)).json()
    assert [s["id"] for s in listed["shows"]] == ["song-1"]

    resp = await client.get("/v1/shows/song-1/bundle", headers=AUTH)
    assert resp.status == 200 and resp.content_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(await resp.read())) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "audio.wav", "project/profile.json"} <= names
        assert json.loads(zf.read("manifest.json"))["title"] == "Dior"
        for key, count in LIGHTS:
            assert len(zf.read(f"frames/{key}.bin")) == 10 * count * 3

    assert (await client.delete("/v1/shows/song-1", headers=AUTH)).status == 204
    assert (await (await client.get("/v1/shows", headers=AUTH)).json())["shows"] == []
    assert (await client.delete("/v1/shows/song-1", headers=AUTH)).status == 404


async def test_replace_keeps_id_and_updates(client):
    await client.put("/v1/shows/song-1", data=bundle(), headers=ZIP)
    resp = await client.put("/v1/shows/song-1", data=bundle(manifest(title="Dior v2")), headers=ZIP)
    assert resp.status == 200
    shows = (await (await client.get("/v1/shows", headers=AUTH)).json())["shows"]
    assert len(shows) == 1 and shows[0]["title"] == "Dior v2"


async def test_bad_bundles_are_refused_and_existing_show_survives(client):
    assert (await client.put("/v1/shows/song-1", data=bundle(), headers=ZIP)).status == 200
    key = LIGHTS[0][0]
    bad = {
        "missing frame file": bundle(drop={f"frames/{key}.bin"}),
        "wrong frame size": bundle(frame_sizes={key: 7}),
        "wrong schema": bundle(manifest(schema="prism-show/0")),
        "missing audio": bundle(drop={"audio"}),
        "missing project": bundle(drop={"project"}),
        "not a zip": b"hello",
    }
    for name, data in bad.items():
        resp = await client.put("/v1/shows/song-1", data=data, headers=ZIP)
        assert resp.status == 400, name
        assert "error" in await resp.json(), name
    shows = (await (await client.get("/v1/shows", headers=AUTH)).json())["shows"]
    assert len(shows) == 1 and shows[0]["title"] == "Dior"
    assert not [p for p in client.shows.root.iterdir() if p.name.startswith(".")]


async def test_wrong_content_type(client):
    resp = await client.put("/v1/shows/song-1", data=bundle(), headers=AUTH)
    assert resp.status == 400


async def test_audio_route_is_public_with_range(client):
    await client.put("/v1/shows/song-1", data=bundle(), headers=ZIP)
    full = await client.get("/v1/shows/song-1/audio")
    assert full.status == 200
    assert full.headers["Content-Type"].startswith("audio/")
    body = await full.read()
    assert body[:4] == b"RIFF"
    part = await client.get("/v1/shows/song-1/audio", headers={"Range": "bytes=4-7"})
    assert part.status == 206
    assert await part.read() == body[4:8]
    assert (await client.get("/v1/shows/nope/audio")).status == 404


async def test_put_fires_the_publish_hook(client, hook_target):
    _, received = hook_target
    assert (await client.put("/v1/shows/a", data=bundle(), headers=ZIP)).status == 200
    await client.hooks.drain()
    events = [r for r in received if r.get("event") == "published"]
    assert len(events) == 1 and events[0]["id"] == "a" and "title" in events[0]
