"""Lights-only backend: no audio, no position, so the engine's clock runs free."""

from __future__ import annotations


class NoneAudio:
    async def start(self, url: str) -> None:
        return None

    async def position(self) -> float | None:
        return None

    async def stop(self) -> None:
        return None
