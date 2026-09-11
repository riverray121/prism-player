from __future__ import annotations

import pytest

from prism_player import config


def test_parse_full_example():
    cfg = config.parse(
        {
            "listen": "0.0.0.0:8760",
            "token_env": "T",
            "data_dir": "/tmp/x",
            "hubs": [{"mac": "1C:C3:AB:BB:C8:5C", "address": "192.168.8.40"}],
            "audio": {
                "backend": "ha",
                "media_player": "media_player.a",
                "audio_url_base": "http://h:8760/",
                "offset_ms": 120,
            },
            "hooks": {"on_play": "http://h/p"},
        }
    )
    assert cfg.listen_port == 8760 and cfg.hubs[0].mac == "1cc3abbbc85c"
    assert cfg.audio.audio_url_base == "http://h:8760" and cfg.audio.offset_ms == 120
    assert cfg.hooks.on_play == "http://h/p" and cfg.hooks.on_stop is None


def test_defaults_and_token(monkeypatch):
    cfg = config.parse(None)
    assert cfg.listen_port == 8760 and cfg.audio.backend == "none"
    with pytest.raises(config.ConfigError):
        _ = cfg.token
    monkeypatch.setenv("PLAYER_TOKEN", "abc")
    assert cfg.token == "abc"


@pytest.mark.parametrize(
    "raw",
    [
        {"listen": "nope"},
        {"hubs": [{"mac": "12"}]},
        {"hubs": [{"mac": "zz", "address": "a"}]},
        {"audio": {"backend": "tape"}},
        {"audio": {"backend": "ha"}},
    ],
)
def test_invalid(raw):
    with pytest.raises(config.ConfigError):
        config.parse(raw)
