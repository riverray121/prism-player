"""The HTTP face: the Companion API plus playback control, bearer-authenticated."""

from __future__ import annotations

import logging
import mimetypes
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiohttp import web

from prism_player import API_VERSION, __version__
from prism_player.config import Config
from prism_player.hooks import Hooks
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
    cfg: Config, token: str, shows: ShowStore, requests: RequestStore, hooks: Hooks
) -> web.Application:
    @web.middleware
    async def auth(request: web.Request, handler: Handler) -> web.StreamResponse:
        if not _is_public(request):
            if request.headers.get("Authorization", "") != f"Bearer {token}":
                return web.json_response({"error": "bearer token required"}, status=401)
        try:
            return await handler(request)
        except (UnknownShow, UnknownRequest) as exc:
            return web.json_response({"error": f"not found: {exc.args[0]}"}, status=404)
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
        created_req, created = requests.create(str(body["title"]), str(body["artist"]), external)
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
            return web.json_response(shows.put(show_id, zip_path))
        finally:
            zip_path.unlink(missing_ok=True)

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
    return app
