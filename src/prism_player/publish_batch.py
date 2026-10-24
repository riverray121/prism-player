"""Batches `on_publish` hook deliveries.

Shows published while other requests are still open or analyzing are held and
delivered together once nothing is pending, so a listener gets one "ready"
message per batch of songs instead of one per show. A stuck request must not
hold a batch forever: anything older than MAX_HOLD_S is delivered regardless.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from prism_player.hooks import Hooks

log = logging.getLogger(__name__)

MAX_HOLD_S = 30 * 60
CHECK_INTERVAL_S = 60


class PublishBatcher:
    def __init__(
        self,
        hooks: Hooks,
        url: str | None,
        pending_requests: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hooks = hooks
        self.url = url
        self.pending_requests = pending_requests
        self.clock = clock
        self.held: list[dict[str, Any]] = []
        self.held_since: float | None = None
        self._task: asyncio.Task[None] | None = None

    def add(self, summary: dict[str, Any]) -> None:
        if self.url is None:
            return
        self.held = [s for s in self.held if s.get("id") != summary.get("id")]
        self.held.append(summary)
        if self.held_since is None:
            self.held_since = self.clock()
        self.check()

    def check(self) -> None:
        """Deliver when nothing is pending or the batch has waited long enough."""
        if not self.held or self.held_since is None:
            return
        pending = self.pending_requests()
        if pending == 0 or self.clock() - self.held_since >= MAX_HOLD_S:
            shows = self.held
            self.held = []
            self.held_since = None
            self.hooks.fire(
                self.url, "published", {"count": len(shows), "shows": shows, "pending": pending}
            )

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_S)
            try:
                self.check()
            except Exception as exc:
                log.warning("publish batch check failed: %s", exc)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
