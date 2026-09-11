"""Click show generation for offset calibration."""

from __future__ import annotations

import json
import wave

from prism_player import calibrate
from prism_player.store import validate_dir


def test_click_frames_are_white_at_clicks_and_black_between():
    data = calibrate.click_frames(pixel_count=2, seconds=2.0, interval=1.0, lit_frames=3)
    frame = 2 * 3
    assert len(data) == 80 * frame
    lit = {i for i in range(80) if data[i * frame : (i + 1) * frame] == b"\xff" * frame}
    assert lit == {0, 1, 2, 40, 41, 42}
    assert data[3 * frame : 40 * frame] == bytes(37 * frame)


def test_click_show_writes_a_valid_bundle_folder(tmp_path):
    folder = tmp_path / "show"
    manifest = calibrate.click_show(
        folder, [("1cc3abbbc85c-0", 4), ("1cc3abbbc85c-1", 3)], seconds=2.0
    )
    assert validate_dir(folder)["frame_count"] == 80
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    with wave.open(str(folder / "audio.wav")) as w:
        assert w.getframerate() == 48_000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 96_000
    assert (folder / "frames" / "1cc3abbbc85c-1.bin").stat().st_size == 80 * 3 * 3
