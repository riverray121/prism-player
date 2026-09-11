"""WLED hubs: discovery by mDNS merged with config, and the JSON API calls the engine needs.

A hub's identity is its MAC (12 lowercase hex digits, as /json/info reports it). A
bundle light key is `<mac>-<output>` where output indexes the hub's configured
outputs with a nonzero length, in /json/cfg order, the same as Prism's rig.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import aiohttp
from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from prism_player.config import HubConfig

log = logging.getLogger(__name__)

WLED_SERVICE = "_wled._tcp.local."
TIMEOUT = aiohttp.ClientTimeout(total=4)


@dataclass
class Output:
    start: int
    count: int


@dataclass
class Hub:
    mac: str
    address: str
    name: str
    outputs: list[Output] = field(default_factory=list)


@dataclass
class Target:
    """A bundle light resolved onto a hub: where its frame bytes go."""

    key: str
    address: str
    start: int
    pixel_count: int


class HubDirectory(Protocol):
    """What the engine needs from the hub layer; tests provide a fake."""

    async def resolve(self, mac: str) -> Hub | None: ...

    async def is_on(self, address: str) -> bool: ...

    async def set_power(self, address: str, on: bool) -> None: ...


def parse_hub(address: str, info: Any, cfg: Any) -> Hub:
    mac = str(info["mac"]).lower()
    name = str(info.get("name", "WLED"))
    ins = cfg.get("hw", {}).get("led", {}).get("ins", []) or []
    outputs = [Output(int(o["start"]), int(o["len"])) for o in ins if int(o.get("len", 0)) > 0]
    return Hub(mac=mac, address=address, name=name, outputs=outputs)


def parse_key(key: str) -> tuple[str, int]:
    mac, _, output = key.rpartition("-")
    return mac, int(output)


class Hubs:
    """Config addresses win over discovered ones; discovery fills in the rest."""

    def __init__(self, session: aiohttp.ClientSession, configured: list[HubConfig]) -> None:
        self.session = session
        self.configured = {h.mac: h.address for h in configured}
        self.discovered: dict[str, str] = {}
        self._zc: AsyncZeroconf | None = None
        self._browser: AsyncServiceBrowser | None = None
        self._pending: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        try:
            self._zc = AsyncZeroconf()
            self._browser = AsyncServiceBrowser(
                self._zc.zeroconf, WLED_SERVICE, handlers=[self._on_change]
            )
        except OSError as exc:
            log.warning("mDNS unavailable, using configured hubs only: %s", exc)

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.async_cancel()
        if self._zc is not None:
            await self._zc.async_close()
        for task in list(self._pending):
            task.cancel()

    def _on_change(
        self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        task = asyncio.create_task(self._learn(zeroconf, service_type, name))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _learn(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(zeroconf, 3000):
            return
        addresses = info.parsed_addresses(IPVersion.V4Only)
        if not addresses:
            return
        address = addresses[0]
        try:
            data = await self._get(address, "/json/info")
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            log.debug("discovered %s at %s did not answer /json/info: %s", name, address, exc)
            return
        mac = str(data.get("mac", "")).lower()
        if mac:
            self.discovered[mac] = address
            log.info("hub %s at %s", mac, address)

    def address_of(self, mac: str) -> str | None:
        return self.configured.get(mac) or self.discovered.get(mac)

    async def _get(self, address: str, path: str) -> Any:
        async with self.session.get(f"http://{address}{path}", timeout=TIMEOUT) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def resolve(self, mac: str) -> Hub | None:
        address = self.address_of(mac)
        if address is None:
            return None
        try:
            info, cfg = await asyncio.gather(
                self._get(address, "/json/info"), self._get(address, "/json/cfg")
            )
            return parse_hub(address, info, cfg)
        except (TimeoutError, aiohttp.ClientError, ValueError, KeyError) as exc:
            log.warning("hub %s at %s unreachable: %s", mac, address, exc)
            return None

    async def is_on(self, address: str) -> bool:
        state = await self._get(address, "/json/state")
        return bool(state.get("on", False))

    async def set_power(self, address: str, on: bool) -> None:
        async with self.session.post(
            f"http://{address}/json/state", json={"on": on}, timeout=TIMEOUT
        ) as r:
            r.raise_for_status()
