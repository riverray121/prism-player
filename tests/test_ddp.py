from __future__ import annotations

import json
from pathlib import Path

from prism_player.ddp import blackout_packets, frame_packets

FIXTURE = Path(__file__).parent / "fixtures" / "ddp_packets.json"


def matrix(frames: int = 3, pixels: int = 4) -> bytes:
    return bytes(i % 251 for i in range(frames * pixels * 3))


def test_header_per_spec():
    (pkt,) = frame_packets(matrix()[0:12])
    assert pkt[0] == 0x41
    assert pkt[1] == 0
    assert pkt[2] == 0x0B
    assert pkt[3] == 0x01
    assert list(pkt[4:8]) == [0, 0, 0, 0]
    assert list(pkt[8:10]) == [0, 12]
    assert len(pkt) == 10 + 12


def test_split_past_480_pixels_push_only_on_last():
    packets = frame_packets(bytes([7]) * 1800)
    assert len(packets) == 2
    assert packets[0][0] == 0x40 and packets[1][0] == 0x41
    assert list(packets[1][4:8]) == [0, 0, 0x05, 0xA0]
    assert list(packets[0][8:10]) == [0x05, 0xA0]
    assert list(packets[1][8:10]) == [0x01, 0x68]
    assert len(packets[0]) + len(packets[1]) == 20 + 1800


def test_base_offset_and_split_resume():
    (pkt,) = frame_packets(matrix()[12:24], 900)
    assert list(pkt[4:8]) == [0, 0, 0x03, 0x84]
    packets = frame_packets(bytes([7]) * 1800, 900)
    assert list(packets[0][4:8]) == [0, 0, 0x03, 0x84]
    assert list(packets[1][4:8]) == [0, 0, 0x09, 0x24]


def test_blackout_is_zeros_at_strip_length():
    (pkt,) = blackout_packets(300)
    assert len(pkt) == 910 and not any(pkt[10:])


def test_matches_shared_fixture():
    cases = json.loads(FIXTURE.read_text())["cases"]
    assert len(cases) == 6
    for case in cases:
        packets = frame_packets(bytes.fromhex(case["frame"]), case["base_offset"])
        assert [p.hex() for p in packets] == case["packets"], case["name"]
