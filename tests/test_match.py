from prism_player.match import best_match, score

SHOWS = [
    {"id": "a", "title": "oh yeah?", "artist": "Steve Lacy"},
    {
        "id": "b",
        "title": "take it from the starz - Slowed & reverb",
        "artist": "Roman Nasenmensch, domi4wave",
    },
    {"id": "c", "title": "Dior", "artist": "Joji"},
]


def test_exact_and_punctuation_insensitive():
    assert best_match("Oh yeah", SHOWS)["id"] == "a"
    assert best_match("oh yeah?", SHOWS)["id"] == "a"


def test_misheard_word_and_partial_title():
    assert best_match("Take It From the Stars", SHOWS)["id"] == "b"
    assert best_match("take it from the starz", SHOWS)["id"] == "b"


def test_artist_and_artist_title():
    assert best_match("joji", SHOWS)["id"] == "c"
    assert best_match("dior by joji", SHOWS)["id"] == "c"


def test_nonsense_is_none():
    assert best_match("zzqx nonsense", SHOWS) is None
    assert best_match("", SHOWS) is None
    assert score("zzqx", "oh yeah?", "Steve Lacy") < 0.6
