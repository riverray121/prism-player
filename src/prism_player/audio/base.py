"""The audio backend interface the engine drives."""

from __future__ import annotations

from typing import Protocol


class AudioBackend(Protocol):
    async def start(self, url: str) -> None:
        """Start playing the audio at url; returns once playback has started."""
        ...

    async def position(self) -> float | None:
        """Current playback position in seconds, or None when unknown."""
        ...

    async def stop(self) -> None: ...
