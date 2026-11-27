import random

from prism_player.history import PlayHistory


def test_fresh_shuffle_puts_recent_plays_last_most_recent_at_the_end(tmp_path):
    h = PlayHistory(tmp_path / "recent.json")
    for s in ["b", "d"]:
        h.record(s)
    for seed in range(20):
        out = h.fresh_shuffle(["a", "b", "c", "d", "e"], random.Random(seed))
        assert set(out[:3]) == {"a", "c", "e"}
        assert out[3:] == ["b", "d"]


def test_fresh_shuffle_still_shuffles_unplayed_shows():
    h = PlayHistory(None)
    orders = {tuple(h.fresh_shuffle(list("abcdefgh"), random.Random(s))) for s in range(10)}
    assert len(orders) > 5


def test_history_persists_and_keeps_one_entry_per_show(tmp_path):
    path = tmp_path / "recent.json"
    h = PlayHistory(path)
    for s in ["a", "b", "a"]:
        h.record(s)
    assert PlayHistory(path).recent == ["b", "a"]
