"""Entry point: serve the API, or run the offset calibration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

from prism_player import calibrate, config
from prism_player.api import build_app
from prism_player.audio.base import AudioBackend
from prism_player.audio.ha import HaBackend
from prism_player.audio.none import NoneAudio
from prism_player.ddp import Sender
from prism_player.engine import Engine
from prism_player.hooks import Hooks
from prism_player.hubs import Hubs
from prism_player.requests import RequestStore
from prism_player.store import ShowStore

log = logging.getLogger("prism_player")


async def serve(cfg: config.Config) -> None:
    token = cfg.token
    shows = ShowStore(cfg.data_dir)
    requests = RequestStore(cfg.data_dir / "requests.sqlite")
    async with aiohttp.ClientSession() as session:
        hooks = Hooks(session)
        hubs = Hubs(session, cfg.hubs)
        sender = Sender()
        engine = Engine(
            shows,
            hubs,
            sender,
            audio_backend(cfg, session),
            hooks,
            audio_url=lambda show_id: f"{cfg.audio.audio_url_base}/v1/shows/{show_id}/audio",
            offset_ms=cfg.audio.offset_ms,
            on_play_url=cfg.hooks.on_play,
            on_stop_url=cfg.hooks.on_stop,
        )
        await hubs.start()
        runner = web.AppRunner(build_app(cfg, token, shows, requests, hooks, engine))
        await runner.setup()
        engine.announce_startup()
        site = web.TCPSite(runner, cfg.listen_host, cfg.listen_port)
        await site.start()
        log.info("listening on %s:%s", cfg.listen_host, cfg.listen_port)
        try:
            await asyncio.Event().wait()
        finally:
            await engine.stop()
            await hubs.stop()
            sender.close()
            await hooks.drain()
            await runner.cleanup()
            requests.close()


def audio_backend(cfg: config.Config, session: aiohttp.ClientSession) -> AudioBackend:
    if cfg.audio.backend == "none":
        return NoneAudio()
    return HaBackend(session, cfg.audio.ha_url, cfg.audio.ha_token, cfg.audio.media_player)


def main() -> None:
    parser = argparse.ArgumentParser(prog="prism-player")
    parser.add_argument("command", choices=["serve", "calibrate"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(name)s %(message)s")
    try:
        cfg = config.load(args.config)
    except (config.ConfigError, OSError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        if args.command == "calibrate":
            asyncio.run(calibrate.run(cfg, audio_backend))
        else:
            asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
