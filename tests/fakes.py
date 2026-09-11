"""Fakes for the engine: a controllable clock, a recording sender, in-memory hubs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from prism_player.hubs import Hub, Output


class FakeClock:
    """Time advances only through sleep, so every frame deadline is deterministic."""

    def __init__(self) -> None:
        self.t = 0.0
        self.late_by = 0.0
        self._gate: asyncio.Event | None = None

    def now(self) -> float:
        return self.t

    def pause(self) -> None:
        """Hold every sleeper until resume, so a show stays mid-frame."""
        self._gate = asyncio.Event()

    def resume(self) -> None:
        if self._gate is not None:
            self._gate.set()
            self._gate = None

    async def sleep(self, seconds: float) -> None:
        if self._gate is not None:
            await self._gate.wait()
        self.t += seconds + self.late_by
        await asyncio.sleep(0)


@dataclass
class Sent:
    t: float
    address: str
    packets: list[bytes]


@dataclass
class FakeSender:
    clock: FakeClock
    sent: list[Sent] = field(default_factory=list)

    def send(self, address: str, packets: list[bytes]) -> None:
        self.sent.append(Sent(self.clock.now(), address, packets))


@dataclass
class FakeHubs:
    hubs: dict[str, Hub] = field(default_factory=dict)
    on: dict[str, bool] = field(default_factory=dict)
    power_calls: list[tuple[str, bool]] = field(default_factory=list)

    def add(self, mac: str, address: str, outputs: list[tuple[int, int]], on: bool) -> None:
        self.hubs[mac] = Hub(mac, address, "WLED", [Output(s, c) for s, c in outputs])
        self.on[address] = on

    async def resolve(self, mac: str) -> Hub | None:
        return self.hubs.get(mac)

    async def is_on(self, address: str) -> bool:
        return self.on[address]

    async def set_power(self, address: str, on: bool) -> None:
        self.power_calls.append((address, on))
        self.on[address] = on
