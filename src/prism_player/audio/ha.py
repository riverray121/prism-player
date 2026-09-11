"""Audio through a Home Assistant media player.

start() calls media_player.play_media with the show's audio URL and waits for the
entity to report playing; position() derives the playhead from the entity's
media_position and media_position_updated_at, fetched at most once a second.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=10)
START_TIMEOUT_S = 15.0
START_POLL_S = 0.25
# A position() call within this window of the last fetch reuses that response.
CACHE_S = 1.0


class HaBackend:
    def __init__(
        self, session: aiohttp.ClientSession, ha_url: str, token: str, entity_id: str
    ) -> None:
        self.session = session
        self.ha_url = ha_url.rstrip("/")
        self.entity_id = entity_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._state: dict[str, Any] | None = None
        self._fetched_at: float = -CACHE_S

    async def _service(self, service: str, data: dict[str, Any]) -> None:
        url = f"{self.ha_url}/api/services/media_player/{service}"
        async with self.session.post(url, json=data, headers=self._headers, timeout=TIMEOUT) as r:
            r.raise_for_status()

    async def _fetch_state(self) -> dict[str, Any]:
        url = f"{self.ha_url}/api/states/{self.entity_id}"
        async with self.session.get(url, headers=self._headers, timeout=TIMEOUT) as r:
            r.raise_for_status()
            state: dict[str, Any] = await r.json()
        self._state = state
        self._fetched_at = time.monotonic()
        return state

    async def start(self, url: str) -> None:
        await self._service(
            "play_media",
            {
                "entity_id": self.entity_id,
                "media_content_id": url,
                "media_content_type": "music",
            },
        )
        deadline = time.monotonic() + START_TIMEOUT_S
        while True:
            state = await self._fetch_state()
            if state.get("state") == "playing":
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"{self.entity_id} did not start playing within {START_TIMEOUT_S:.0f} s"
                )
            await asyncio.sleep(START_POLL_S)

    async def position(self) -> float | None:
        if time.monotonic() - self._fetched_at >= CACHE_S:
            try:
                await self._fetch_state()
            except (TimeoutError, aiohttp.ClientError) as exc:
                log.warning("state fetch for %s failed: %s", self.entity_id, exc)
                return None
        return position_from_state(self._state, datetime.now(UTC))

    async def stop(self) -> None:
        try:
            await self._service("media_stop", {"entity_id": self.entity_id})
        except (TimeoutError, aiohttp.ClientError) as exc:
            log.warning("media_stop for %s failed: %s", self.entity_id, exc)


def position_from_state(state: dict[str, Any] | None, now: datetime) -> float | None:
    """Playhead in seconds from a media_player state, or None when not playing."""
    if state is None or state.get("state") != "playing":
        return None
    attrs = state.get("attributes") or {}
    position = attrs.get("media_position")
    updated = attrs.get("media_position_updated_at")
    if not isinstance(position, int | float) or not isinstance(updated, str):
        return None
    try:
        updated_at = datetime.fromisoformat(updated)
    except ValueError:
        return None
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return float(position) + (now - updated_at).total_seconds()
