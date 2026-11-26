import pytest

from prism_player.palettes import PALETTES, UnknownPalette, _linear, colors_for_show, recolor


def test_colors_are_three_neighbors_and_stable_per_show():
    linear = [_linear(c) for c in PALETTES["indie-dusk"]]
    for show_id in ("a", "b", "c", "some-uuid"):
        colors = colors_for_show("indie-dusk", show_id, 5)
        assert len(colors) == 5
        assert colors == colors_for_show("indie-dusk", show_id, 5)
        indexes = sorted({linear.index(c) for c in colors})
        assert len(indexes) == 3 and indexes[-1] - indexes[0] == 2


def test_hex_colors_are_converted_to_linear_values():
    assert _linear("#FFFFFF") == (255, 255, 255)
    assert _linear("#000000") == (0, 0, 0)
    assert _linear("#E8705A") == (207, 42, 26)  # coral stays coral on gamma-less LEDs


def test_recolor_keeps_each_pixel_value_and_takes_the_color():
    frames = bytes([100, 50, 0, 0, 0, 0, 255, 255, 255])
    out = recolor(frames, (200, 100, 0))
    assert out == bytes([78, 39, 0, 0, 0, 0, 200, 100, 0])
    assert len(out) == len(frames)


def test_unknown_palette_raises():
    with pytest.raises(UnknownPalette):
        colors_for_show("nope", "a", 2)
