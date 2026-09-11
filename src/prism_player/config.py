"""Configuration: one YAML file. Secrets come from the environment variables it names."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass
class HubConfig:
    mac: str
    address: str


@dataclass
class AudioConfig:
    backend: str = "none"
    ha_url: str = "http://127.0.0.1:8123"
    ha_token_env: str = "HA_TOKEN"
    media_player: str = ""
    audio_url_base: str = ""
    offset_ms: int = 0


@dataclass
class HooksConfig:
    on_request: str | None = None
    on_play: str | None = None
    on_stop: str | None = None


@dataclass
class Config:
    listen_host: str = "0.0.0.0"
    listen_port: int = 8760
    token_env: str = "PLAYER_TOKEN"
    data_dir: Path = Path("./data")
    hubs: list[HubConfig] = field(default_factory=list)
    audio: AudioConfig = field(default_factory=AudioConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)

    @property
    def token(self) -> str:
        value = os.environ.get(self.token_env, "")
        if not value:
            raise ConfigError(f"environment variable {self.token_env} (the bearer token) is unset")
        return value


AUDIO_BACKENDS = ("ha", "none")


def _expect(mapping: Any, name: str) -> dict[str, Any]:
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise ConfigError(f"{name} must be a mapping")
    return mapping


def parse(raw: Any) -> Config:
    top = _expect(raw, "config")
    cfg = Config()
    listen = str(top.get("listen", f"{cfg.listen_host}:{cfg.listen_port}"))
    host, sep, port = listen.rpartition(":")
    if not sep or not port.isdigit():
        raise ConfigError(f"listen must be host:port, got {listen!r}")
    cfg.listen_host, cfg.listen_port = host, int(port)
    cfg.token_env = str(top.get("token_env", cfg.token_env))
    cfg.data_dir = Path(str(top.get("data_dir", cfg.data_dir)))

    hubs = top.get("hubs") or []
    if not isinstance(hubs, list):
        raise ConfigError("hubs must be a list")
    for i, hub in enumerate(hubs):
        hub = _expect(hub, f"hubs[{i}]")
        if "mac" not in hub or "address" not in hub:
            raise ConfigError(f"hubs[{i}] needs mac and address")
        cfg.hubs.append(HubConfig(mac=_norm_mac(str(hub["mac"])), address=str(hub["address"])))

    audio = _expect(top.get("audio"), "audio")
    cfg.audio = AudioConfig(
        backend=str(audio.get("backend", "none")),
        ha_url=str(audio.get("ha_url", cfg.audio.ha_url)).rstrip("/"),
        ha_token_env=str(audio.get("ha_token_env", cfg.audio.ha_token_env)),
        media_player=str(audio.get("media_player", "")),
        audio_url_base=str(audio.get("audio_url_base", "")).rstrip("/"),
        offset_ms=int(audio.get("offset_ms", 0)),
    )
    if cfg.audio.backend not in AUDIO_BACKENDS:
        raise ConfigError(f"audio.backend must be one of {AUDIO_BACKENDS}")
    if cfg.audio.backend == "ha":
        for key in ("media_player", "audio_url_base"):
            if not getattr(cfg.audio, key):
                raise ConfigError(f"audio.{key} is required for the ha backend")

    hooks = _expect(top.get("hooks"), "hooks")
    cfg.hooks = HooksConfig(
        on_request=_opt_str(hooks.get("on_request")),
        on_play=_opt_str(hooks.get("on_play")),
        on_stop=_opt_str(hooks.get("on_stop")),
    )
    return cfg


def _opt_str(value: Any) -> str | None:
    return str(value) if value else None


def _norm_mac(mac: str) -> str:
    """WLED reports the MAC as 12 lowercase hex digits; accept separators on input."""
    digits = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    if len(digits) != 12:
        raise ConfigError(f"hub mac must be 12 hex digits, got {mac!r}")
    return digits


def load(path: Path) -> Config:
    with path.open() as f:
        return parse(yaml.safe_load(f))
