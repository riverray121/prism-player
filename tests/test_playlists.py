from __future__ import annotations

from prism_player.ddp import HEADER_BYTES
from prism_player.palettes import color_track, colors_for_show, recolor
from tests.bundles import FRAME_COUNT, FRAME_RATE, LIGHTS, bundle, frames, manifest
from tests.conftest import AUTH
from tests.test_playback_api import wait_idle

ZIP = {"Content-Type": "application/zip", **AUTH}
MAC = "1cc3abbbc85c"
CHILL = "spotify:track:chill1"


async def publish(client, show_id: str, uri: str, title: str) -> None:
    """A request for the URI, published as show_id, as Prism does it."""
    resp = await client.post(
        "/v1/requests",
        json={"title": title, "artist": "A", "external": {"spotify_uri": uri}},
        headers=AUTH,
    )
    req = await resp.json()
    m = manifest(title=title, external={"spotify_uri": uri}, request_id=req["id"])
    assert (await client.put(f"/v1/shows/{show_id}", data=bundle(m), headers=ZIP)).status == 200
    body = {"status": "published", "show_id": show_id}
    assert (await client.patch(f"/v1/requests/{req['id']}", json=body, headers=AUTH)).status == 200


async def test_put_and_list_resolve_published_shows(client):
    await publish(client, "s1", CHILL, "Ivy")
    resp = await client.put(
        "/v1/playlists/Prism Chill",
        json={"spotify_uris": [CHILL, "spotify:track:not-yet"], "palette": "indie-dusk"},
        headers=AUTH,
    )
    assert resp.status == 200
    assert (await resp.json())["show_ids"] == ["s1"]
    listed = (await (await client.get("/v1/playlists", headers=AUTH)).json())["playlists"]
    assert [(p["name"], p["palette"], p["show_ids"]) for p in listed] == [
        ("Prism Chill", "indie-dusk", ["s1"])
    ]


async def test_bad_palette_and_unknown_playlist(client):
    body = {"spotify_uris": [], "palette": "nope"}
    assert (await client.put("/v1/playlists/x", json=body, headers=AUTH)).status == 400
    resp = await client.post("/v1/play", json={"playlist": "missing"}, headers=AUTH)
    assert resp.status == 404
    assert (await client.delete("/v1/playlists/missing", headers=AUTH)).status == 404


async def test_empty_playlist_404s_with_a_reason(client):
    await client.put("/v1/playlists/Prism Chill", json={"spotify_uris": [CHILL]}, headers=AUTH)
    resp = await client.post("/v1/play", json={"playlist": "prism chill"}, headers=AUTH)
    assert resp.status == 404
    assert "no playable shows" in (await resp.json())["error"]


async def test_spoken_names_play_the_playlist(client):
    client.hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=True)
    await publish(client, "s1", CHILL, "Ivy")
    await publish(client, "s2", "spotify:track:chill2", "Dior")
    body = {"spotify_uris": [CHILL, "spotify:track:chill2"]}
    await client.put("/v1/playlists/Prism Chill", json=body, headers=AUTH)
    client.clock.pause()
    for spoken in ("Prism chill", "the chill playlist", "prison chill", "chill"):
        resp = await client.post("/v1/play", json={"query": spoken}, headers=AUTH)
        assert resp.status == 200, spoken
        status = await resp.json()
        assert {status["show"]["id"], *status["queue"]} == {"s1", "s2"}
        assert status["playlist"] == "Prism Chill"
        await client.post("/v1/stop", headers=AUTH)


async def test_song_query_still_plays_the_song(client):
    client.hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=True)
    await publish(client, "s1", CHILL, "Ivy")
    await client.put("/v1/playlists/Prism Chill", json={"spotify_uris": [CHILL]}, headers=AUTH)
    client.clock.pause()
    resp = await client.post("/v1/play", json={"query": "ivy"}, headers=AUTH)
    assert (await resp.json())["show"]["id"] == "s1"
    await client.post("/v1/stop", headers=AUTH)


async def test_palette_playlist_recolors_its_shows_only(client):
    client.hubs.add(MAC, "10.0.0.5", [(0, 4), (4, 3)], on=True)
    await publish(client, "s1", CHILL, "Ivy")
    await publish(client, "s2", "spotify:track:other", "Dior")
    body = {"spotify_uris": [CHILL], "palette": "indie-dusk"}
    await client.put("/v1/playlists/Prism Chill", json=body, headers=AUTH)

    resp = await client.post("/v1/play", json={"show": "s1"}, headers=AUTH)
    assert (await resp.json())["show"]["palette"] == "indie-dusk"
    await wait_idle(client.engine)
    first = client.sender.sent[0].packets[0][HEADER_BYTES:]
    pixels = LIGHTS[0][1]
    cycle = colors_for_show("indie-dusk", "s1", len(LIGHTS))[0]
    track = color_track(cycle, FRAME_COUNT, FRAME_RATE)
    assert first == recolor(frames(pixels), pixels, track)[: pixels * 3]

    client.sender.sent.clear()
    resp = await client.post("/v1/play", json={"show": "s2"}, headers=AUTH)
    assert (await resp.json())["show"]["palette"] is None
    await wait_idle(client.engine)
    assert client.sender.sent[0].packets[0][HEADER_BYTES:] == frames(pixels)[: pixels * 3]
