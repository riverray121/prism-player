"""Outbound webhooks: fire and forget, a failure is logged and nothing else."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class Hooks:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self._pending: set[asyncio.Task[None]] = set()

    def fire(self, url: str | None, event: str, payload: dict[str, Any]) -> None:
        if not url:
            return
        task = asyncio.create_task(self._post(url, {"event": event, **payload}))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _post(self, url: str, body: dict[str, Any]) -> None:
        try:
            async with self.session.post(url, json=body, timeout=aiohttp.ClientTimeout(10)) as r:
                if r.status >= 400:
                    log.warning("hook %s answered %s", url, r.status)
        except Exception as exc:
            log.warning("hook %s failed: %s", url, exc)

    async def drain(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
