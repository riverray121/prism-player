"""Palette recoloring: a show keeps its brightness and rhythm, and its colors
come from a named palette instead.

Each light of a show gets one palette color. A show draws three neighboring
colors from the palette (neighbors in the palette's order go together) and
spreads them over its lights; the choice is seeded by the show id, so a show
looks the same every time it plays. Every pixel keeps its original value
(the largest of its three channels) and takes the light's palette color at
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
        "#F4A259",  # amber
        "#E8705A",  # coral
        "#D45D79",  # dusty rose
        "#8E4A8C",  # plum
        "#5B4B9A",  # dusk violet
        "#2E7D8C",  # deep teal
    ],
}
GAMMA = 2.2
SPAN = 3  # neighboring palette colors per show

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


def colors_for_show(palette: str, show_id: str, light_count: int) -> list[RGB]:
    """One linear RGB color per light, the same for a given show every time."""
    if palette not in PALETTES:
        raise UnknownPalette(palette)
    colors = PALETTES[palette]
    rng = random.Random(show_id)
    span = min(SPAN, len(colors))
    start = rng.randrange(len(colors) - span + 1)
    chosen = colors[start : start + span]
    rng.shuffle(chosen)
    return [_linear(chosen[i % span]) for i in range(light_count)]


def recolor(frames: bytes, color: RGB) -> bytes:
    """Every pixel of every frame becomes `color` scaled by the pixel's value."""
    px = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
    value = px.max(axis=1).astype(np.float32) / 255.0
    out = np.rint(value[:, None] * np.asarray(color, dtype=np.float32)[None, :])
    return bytes(out.astype(np.uint8).tobytes())
