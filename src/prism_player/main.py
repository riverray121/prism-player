"""Entry point: serve the API, or run the offset calibration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

from prism_player import config
from prism_player.api import build_app
from prism_player.hooks import Hooks
from prism_player.requests import RequestStore
from prism_player.store import ShowStore

log = logging.getLogger("prism_player")


async def serve(cfg: config.Config) -> None:
    token = cfg.token
    shows = ShowStore(cfg.data_dir)
    requests = RequestStore(cfg.data_dir / "requests.sqlite")
    async with aiohttp.ClientSession() as session:
        hooks = Hooks(session)
        runner = web.AppRunner(build_app(cfg, token, shows, requests, hooks))
        await runner.setup()
        site = web.TCPSite(runner, cfg.listen_host, cfg.listen_port)
        await site.start()
        log.info("listening on %s:%s", cfg.listen_host, cfg.listen_port)
        try:
            await asyncio.Event().wait()
        finally:
            await hooks.drain()
            await runner.cleanup()
            requests.close()


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
    if args.command == "calibrate":
        print("calibrate is not built yet", file=sys.stderr)
        sys.exit(2)
    try:
        asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
