"""Fuzzy show lookup for spoken queries.

Speech recognition and spelling drift apart ("stars" for "starz", a dropped
question mark), so a query is scored against each show's title and against
"artist title" with difflib, plus a per-word pass so a partial title still
wins. The best show above the threshold is the match.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

THRESHOLD = 0.6

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return _NON_WORD.sub(" ", text.lower()).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _word_score(query: str, candidate: str) -> float:
    """Fraction of query words that closely match some candidate word."""
    words = query.split()
    if not words:
        return 0.0
    hits = 0
    for w in words:
        if any(_ratio(w, c) >= 0.8 for c in candidate.split()):
            hits += 1
    return hits / len(words)


def score(query: str, title: str, artist: str) -> float:
    q = normalize(query)
    t = normalize(title)
    at = normalize(f"{artist} {title}")
    if not q:
        return 0.0
    if q == t or q in t:
        return 1.0
    return max(_ratio(q, t), _ratio(q, at), _word_score(q, t), _word_score(q, at))


def best_match(query: str, shows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The show scoring highest for the query, or None under the threshold."""
    best: tuple[float, dict[str, Any]] | None = None
    for show in shows:
        s = score(query, str(show.get("title", "")), str(show.get("artist", "")))
        if best is None or s > best[0]:
            best = (s, show)
    if best is None or best[0] < THRESHOLD:
        return None
    return best[1]
