"""DDP packet assembly and sending (spec: http://www.3waylabs.com/ddp/).

Byte layout matches Prism's live streamer (src/lib/hardware/ddp.ts): version 1
flags, RGB 8-bit data type, destination 1, big-endian offset and length, frames
past 480 pixels split into 1440-byte payloads with PUSH on the last packet only.
"""

from __future__ import annotations

import socket

DDP_PORT = 4048

FLAG_VER1 = 0x40
FLAG_PUSH = 0x01
TYPE_RGB8 = 0x0B
ID_DEFAULT = 0x01
HEADER_BYTES = 10
MAX_DATA_BYTES = 1440


def packet(payload: bytes, offset: int, push: bool) -> bytes:
    header = bytes(
        (
            FLAG_VER1 | (FLAG_PUSH if push else 0),
            0,
            TYPE_RGB8,
            ID_DEFAULT,
            (offset >> 24) & 0xFF,
            (offset >> 16) & 0xFF,
            (offset >> 8) & 0xFF,
            offset & 0xFF,
            (len(payload) >> 8) & 0xFF,
            len(payload) & 0xFF,
        )
    )
    return header + payload


def frame_packets(frame: bytes | memoryview, base_offset: int = 0) -> list[bytes]:
    """Packets for one RGB frame placed at byte base_offset in the hub's buffer.

    WLED's DDP buffer spans every output concatenated, so a light on a multi-output
    hub lands at its output's start pixel times 3.
    """
    data = bytes(frame)
    packets = []
    for off in range(0, len(data), MAX_DATA_BYTES):
        chunk = data[off : off + MAX_DATA_BYTES]
        last = off + MAX_DATA_BYTES >= len(data)
        packets.append(packet(chunk, base_offset + off, last))
    return packets


def blackout_packets(pixel_count: int, base_offset: int = 0) -> list[bytes]:
    return frame_packets(bytes(pixel_count * 3), base_offset)


class Sender:
    """One UDP socket for every hub. Sends never block; a full buffer drops the packet."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def send(self, address: str, packets: list[bytes]) -> None:
        for pkt in packets:
            try:
                self.sock.sendto(pkt, (address, DDP_PORT))
            except (BlockingIOError, OSError):
                pass

    def close(self) -> None:
        self.sock.close()
