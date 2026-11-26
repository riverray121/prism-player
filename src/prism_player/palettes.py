"""Palette recoloring: a show keeps its brightness and rhythm, and its colors
come from a named palette instead.

A show draws SPAN neighboring colors from the palette (neighbors in the
palette's order go together). Each light steps through those colors over the
song, fading from one to the next every STEP_S seconds, starting at its own
point in the cycle, so the lights differ from each other and the room
changes as the song goes on. The choice is seeded by the show id, so a show
looks the same every time it plays. Every pixel keeps its original value
(the largest of its three channels) and takes its light's current color at
that value.

WLED sends realtime frames to the LEDs without gamma correction, so palette
colors, written as sRGB hex, are converted to linear values first. Without
that, mid-range channels come out too bright and a coral reads as yellow.
"""

from __future__ import annotations

import random

import numpy as np

# Warm to cool. Pale and near-black tones are left out: LEDs show pale colors
# as white and dark ones as dim brown.
PALETTES: dict[str, list[str]] = {
    "indie-dusk": [
        "#F2B33D",  # golden amber
        "#F4A259",  # amber
        "#F08A4B",  # tangerine
        "#E8705A",  # coral
        "#D45D79",  # dusty rose
        "#C2508F",  # magenta rose
        "#8E4A8C",  # plum
        "#5B4B9A",  # dusk violet
        "#3F6FA8",  # twilight blue
        "#2E7D8C",  # deep teal
    ],
}
GAMMA = 2.2
SPAN = 4  # neighboring palette colors per show
STEP_S = 20.0  # seconds from one color to the next on a light

RGB = tuple[int, int, int]


class UnknownPalette(KeyError):
    pass


def _linear(hex_color: str) -> RGB:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return (
        round(255 * (r / 255) ** GAMMA),
        round(255 * (g / 255) ** GAMMA),
        round(255 * (b / 255) ** GAMMA),
    )


def colors_for_show(palette: str, show_id: str, light_count: int) -> list[list[RGB]]:
    """Per light, the cycle of linear colors it steps through; the same for a
    given show every time. Every light uses the show's SPAN colors, each
    starting at a different one."""
    if palette not in PALETTES:
        raise UnknownPalette(palette)
    colors = PALETTES[palette]
    rng = random.Random(show_id)
    span = min(SPAN, len(colors))
    start = rng.randrange(len(colors) - span + 1)
    chosen = [_linear(c) for c in colors[start : start + span]]
    rng.shuffle(chosen)
    return [chosen[i % span :] + chosen[: i % span] for i in range(light_count)]


def color_track(cycle: list[RGB], frame_count: int, frame_rate_hz: float) -> np.ndarray:
    """A (frame_count, 3) array of the light's color at each frame: STEP_S on
    each color of the cycle, a cosine fade into the next over the step's
    second half."""
    t = np.arange(frame_count, dtype=np.float32) / np.float32(frame_rate_hz) / STEP_S
    step = np.floor(t).astype(np.int64)
    frac = t - step
    fade = np.clip((frac - 0.5) * 2.0, 0.0, 1.0)
    w = (0.5 - 0.5 * np.cos(np.pi * fade))[:, None]
    palette = np.asarray(cycle, dtype=np.float32)
    a = palette[step % len(cycle)]
    b = palette[(step + 1) % len(cycle)]
    return (a * (1.0 - w) + b * w).astype(np.float32)


def recolor(frames: bytes, pixel_count: int, colors: np.ndarray) -> bytes:
    """Every pixel of frame i becomes colors[i] scaled by the pixel's value."""
    px = np.frombuffer(frames, dtype=np.uint8).reshape(len(colors), pixel_count, 3)
    value = px.max(axis=2).astype(np.float32) / 255.0
    out = np.rint(value[:, :, None] * colors[:, None, :])
    return bytes(out.astype(np.uint8).tobytes())
