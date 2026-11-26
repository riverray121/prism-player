import numpy as np
import pytest

from prism_player.palettes import (
    PALETTES,
    SPAN,
    STEP_S,
    UnknownPalette,
    _linear,
    color_track,
    colors_for_show,
    recolor,
)


def test_each_show_uses_neighboring_colors_and_lights_start_apart():
    linear = [_linear(c) for c in PALETTES["indie-dusk"]]
    starts = set()
    for show_id in [f"show-{n}" for n in range(40)]:
        cycles = colors_for_show("indie-dusk", show_id, 5)
        assert cycles == colors_for_show("indie-dusk", show_id, 5)
        used = sorted({linear.index(c) for cycle in cycles for c in cycle})
        assert len(used) == SPAN and used[-1] - used[0] == SPAN - 1
        assert len({cycle[0] for cycle in cycles[:SPAN]}) == SPAN
        starts.add(used[0])
    # Different shows land on different stretches of the palette.
    assert len(starts) >= 4


def test_hex_colors_are_converted_to_linear_values():
    assert _linear("#FFFFFF") == (255, 255, 255)
    assert _linear("#000000") == (0, 0, 0)
    assert _linear("#E8705A") == (207, 42, 26)  # coral stays coral on gamma-less LEDs


def test_track_holds_then_fades_to_the_next_color():
    cycle = [(200, 0, 0), (0, 0, 200)]
    rate = 10.0
    track = color_track(cycle, int(STEP_S * rate * 2), rate)
    assert tuple(track[0]) == (200, 0, 0)
    assert tuple(track[int(STEP_S * rate * 0.4)]) == (200, 0, 0)  # first half holds
    mid = track[int(STEP_S * rate * 0.75)]
    assert mid[0] == pytest.approx(100, abs=1) and mid[2] == pytest.approx(100, abs=1)
    assert tuple(track[int(STEP_S * rate)]) == (0, 0, 200)


def test_recolor_keeps_each_pixel_value_and_takes_the_frame_color():
    frames = bytes([100, 50, 0, 0, 0, 0, 255, 255, 255, 255, 0, 0])  # 2 frames x 2 px
    colors = np.array([[200, 100, 0], [0, 0, 100]], dtype=np.float32)
    out = recolor(frames, 2, colors)
    assert out == bytes([78, 39, 0, 0, 0, 0, 0, 0, 100, 0, 0, 100])


def test_unknown_palette_raises():
    with pytest.raises(UnknownPalette):
        colors_for_show("nope", "a", 2)
