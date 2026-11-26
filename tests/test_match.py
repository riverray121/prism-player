from prism_player.match import best_match, score

SHOWS = [
    {"id": "a", "title": "oh yeah?", "artist": "Steve Lacy"},
    {
        "id": "b",
        "title": "take it from the starz - Slowed & reverb",
        "artist": "Roman Nasenmensch, domi4wave",
    },
    {"id": "c", "title": "Dior", "artist": "Joji"},
    {"id": "d", "title": "Ivy", "artist": "Butter Bath, Nice Guys"},
    {"id": "e", "title": "Stand by Me", "artist": "Ben E. King"},
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


def test_title_by_misheard_artist():
    assert best_match("IV by Potterbat", SHOWS)["id"] == "d"
    assert best_match("ivy by butter bath", SHOWS)["id"] == "d"


def test_by_inside_a_title():
    assert best_match("stand by me", SHOWS)["id"] == "e"
    assert best_match("stand by me by ben e king", SHOWS)["id"] == "e"


def test_right_artist_wrong_title_is_none():
    assert best_match("purple rain by butter bath", SHOWS) is None


def test_nonsense_is_none():
    assert best_match("zzqx nonsense", SHOWS) is None
    assert best_match("", SHOWS) is None
    assert score("zzqx", "oh yeah?", "Steve Lacy") < 0.6
