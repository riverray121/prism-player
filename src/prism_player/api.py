"""The HTTP face: the Companion API plus playback control, bearer-authenticated."""

from __future__ import annotations

import logging
import mimetypes
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from prism_player import API_VERSION, __version__
from prism_player.config import Config
from prism_player.engine import Engine
from prism_player.hooks import Hooks
from prism_player.match import best_match
from prism_player.palettes import PALETTES, UnknownPalette
from prism_player.playlists import PlaylistStore, UnknownPlaylist, show_ids
from prism_player.publish_batch import PublishBatcher
from prism_player.requests import STATUSES, RequestStore, UnknownRequest
from prism_player.store import BadBundle, ShowStore, UnknownShow

log = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _is_public(request: web.Request) -> bool:
    if request.path == "/healthz":
        return True
    # The media player fetches audio with no headers; the show id is the only guard.
    return request.method == "GET" and request.match_info.route.name == "audio"


def build_app(
    cfg: Config,
    token: str,
    shows: ShowStore,
    requests: RequestStore,
    hooks: Hooks,
    engine: Engine,
    batcher: PublishBatcher | None = None,
    playlists: PlaylistStore | None = None,
) -> web.Application:
    playlist_store = playlists or PlaylistStore(cfg.data_dir / "playlists.sqlite")

    @web.middleware
    async def auth(request: web.Request, handler: Handler) -> web.StreamResponse:
        if not _is_public(request):
            if request.headers.get("Authorization", "") != f"Bearer {token}":
                return web.json_response({"error": "bearer token required"}, status=401)
        try:
            return await handler(request)
        except (UnknownShow, UnknownRequest, UnknownPlaylist) as exc:
            return web.json_response({"error": f"not found: {exc.args[0]}"}, status=404)
        except UnknownPalette as exc:
            return web.json_response({"error": f"unknown palette: {exc.args[0]}"}, status=400)
        except BadBundle as exc:
            return web.json_response({"error": f"bad bundle: {exc}"}, status=400)
        except (KeyError, ValueError, TypeError) as exc:
            return web.json_response({"error": f"bad request: {exc}"}, status=400)

    async def healthz(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def info(_request: web.Request) -> web.Response:
        return web.json_response(
            {"name": "prism-player", "version": __version__, "api": API_VERSION}
        )

    async def list_requests(_request: web.Request) -> web.Response:
        return web.json_response({"requests": requests.list()})

    async def create_request(request: web.Request) -> web.Response:
        body = await request.json()
        external = body.get("external") or {}
        if not isinstance(external, dict):
            raise ValueError("external must be an object")
        duration = body.get("duration_s")
        created_req, created = requests.create(
            str(body["title"]),
            str(body["artist"]),
            external,
            float(duration) if duration is not None else None,
        )
        if created:
            hooks.fire(cfg.hooks.on_request, "request", created_req)
        return web.json_response(created_req, status=201 if created else 200)

    async def patch_request(request: web.Request) -> web.Response:
        body = await request.json()
        status = str(body["status"])
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        show_id = body.get("show_id")
        updated = requests.update(
            request.match_info["id"], status, str(show_id) if show_id is not None else None
        )
        # A removed song leaves the player: its show goes, so neither a name
        # query nor a playlist can play it.
        if status == "removed" and updated["show_id"] and shows.exists(updated["show_id"]):
            shows.delete(updated["show_id"])
        return web.json_response(updated)

    async def list_shows(_request: web.Request) -> web.Response:
        return web.json_response({"shows": shows.list()})

    async def put_show(request: web.Request) -> web.Response:
        show_id = request.match_info["id"]
        if request.content_type != "application/zip":
            raise ValueError("body must be application/zip")
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            async for chunk in request.content.iter_chunked(1 << 16):
                tmp.write(chunk)
            zip_path = Path(tmp.name)
        try:
            summary = shows.put(show_id, zip_path)
        finally:
            zip_path.unlink(missing_ok=True)
        if batcher is not None:
            batcher.add(summary)
        else:
            hooks.fire(cfg.hooks.on_publish, "published", summary)
        return web.json_response(summary)

    async def get_bundle(request: web.Request) -> web.StreamResponse:
        show_id = request.match_info["id"]
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            zip_path = Path(tmp.name)
        try:
            shows.bundle(show_id, zip_path)
            response = web.StreamResponse(
                headers={
                    "Content-Type": "application/zip",
                    "Content-Length": str(zip_path.stat().st_size),
                    "Content-Disposition": f'attachment; filename="{show_id}.zip"',
                }
            )
            await response.prepare(request)
            with zip_path.open("rb") as f:
                while chunk := f.read(1 << 16):
                    await response.write(chunk)
            await response.write_eof()
            return response
        finally:
            zip_path.unlink(missing_ok=True)

    async def delete_show(request: web.Request) -> web.Response:
        shows.delete(request.match_info["id"])
        return web.Response(status=204)

    async def audio(request: web.Request) -> web.StreamResponse:
        path = shows.audio_path(request.match_info["id"])
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return web.FileResponse(path, headers={"Content-Type": content_type})

    def _miss_reason(query: str) -> str:
        """Why a query played nothing: a request for the song still in the
        pipeline is a different answer from an unknown song, and the voice
        agent relays the reason as spoken."""
        pending = [r for r in requests.list() if r["status"] in ("open", "analyzing")]
        hit = best_match(query, pending)
        if hit is not None:
            return f"{hit['title']!r} is still being analyzed; try again in a few minutes"
        return f"no show matches {query!r}"

    def _playlist_view(p: dict[str, Any]) -> dict[str, Any]:
        ids = show_ids(p, requests, shows)
        # The palette's hex colors, for clients that draw the playlist.
        colors = PALETTES.get(p["palette"]) if p["palette"] else None
        return {**p, "show_ids": ids, "colors": colors}

    async def list_playlists(_request: web.Request) -> web.Response:
        return web.json_response({"playlists": [_playlist_view(p) for p in playlist_store.list()]})

    async def put_playlist(request: web.Request) -> web.Response:
        body = await request.json()
        uris = body["spotify_uris"]
        if not isinstance(uris, list):
            raise ValueError("spotify_uris must be a list")
        palette = body.get("palette")
        p = playlist_store.put(request.match_info["name"], uris, str(palette) if palette else None)
        return web.json_response(_playlist_view(p))

    async def delete_playlist(request: web.Request) -> web.Response:
        playlist_store.delete(request.match_info["name"])
        return web.Response(status=204)

    async def _play_playlist(p: dict[str, Any], shuffle: bool) -> web.Response:
        ids = show_ids(p, requests, shows)
        if not ids:
            return web.json_response(
                {"error": f"playlist {p['name']!r} has no playable shows yet"}, status=404
            )
        if shuffle:
            ids = engine.history.fresh_shuffle(ids)
        await engine.play(ids, playlist=str(p["name"]))
        return web.json_response(engine.status())

    async def play(request: web.Request) -> web.Response:
        body = await request.json()
        if "playlist" in body:
            p = playlist_store.get(str(body["playlist"]))
            return await _play_playlist(p, bool(body.get("shuffle", True)))
        if "query" in body:
            query = str(body["query"])
            # A spoken playlist name ("prism chill") plays the playlist shuffled.
            named = playlist_store.match(query)
            if named is not None:
                return await _play_playlist(named, True)
            matched = best_match(query, shows.list())
            if matched is None:
                return web.json_response({"error": _miss_reason(query)}, status=404)
            await engine.play([str(matched["id"])])
        elif "show" in body:
            await engine.play([str(body["show"])])
        elif body.get("queue") == "all":
            await engine.play_all(shuffle=bool(body.get("shuffle", False)))
        elif isinstance(body.get("queue"), list):
            await engine.play([str(s) for s in body["queue"]])
        else:
            raise ValueError("body needs query, show, playlist, queue: [ids], or queue: all")
        return web.json_response(engine.status())

    async def stop(_request: web.Request) -> web.Response:
        await engine.stop()
        return web.json_response(engine.status())

    async def next_show(_request: web.Request) -> web.Response:
        await engine.next()
        return web.json_response(engine.status())

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(engine.status())

    app = web.Application(middlewares=[auth], client_max_size=1 << 30)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/v1/info", info)
    app.router.add_get("/v1/requests", list_requests)
    app.router.add_post("/v1/requests", create_request)
    app.router.add_patch("/v1/requests/{id}", patch_request)
    app.router.add_get("/v1/shows", list_shows)
    app.router.add_put("/v1/shows/{id}", put_show)
    app.router.add_get("/v1/shows/{id}/bundle", get_bundle)
    app.router.add_delete("/v1/shows/{id}", delete_show)
    app.router.add_get("/v1/shows/{id}/audio", audio, name="audio")
    app.router.add_get("/v1/playlists", list_playlists)
    app.router.add_put("/v1/playlists/{name}", put_playlist)
    app.router.add_delete("/v1/playlists/{name}", delete_playlist)
    app.router.add_post("/v1/play", play)
    app.router.add_post("/v1/stop", stop)
    app.router.add_post("/v1/next", next_show)
    app.router.add_get("/v1/status", status)
    return app
