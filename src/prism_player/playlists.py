"""Named playlists: song lists pushed by an outside sync, played as a queue,
optionally with a palette applied to their shows.

A playlist holds Spotify track URIs, not show ids: the sync knows the
playlist, while the show for a track appears later, when Prism publishes the
request carrying that URI. Show ids are resolved from the requests at play
time, so a song analyzed after the last sync still plays.
"""

from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from prism_player.palettes import PALETTES, UnknownPalette
from prism_player.requests import RequestStore
from prism_player.store import ShowStore

# Words a spoken playlist name carries that the stored name does not.
_FILLER = {"the", "my", "playlist", "prism"}
MATCH_THRESHOLD = 0.85


class UnknownPlaylist(KeyError):
    pass


def _key(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def _core(name: str) -> str:
    return " ".join(w for w in _key(name).split() if w not in _FILLER)


class PlaylistStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS playlists (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                spotify_uris TEXT NOT NULL,
                palette TEXT
            )"""
        )
        self.con.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "name": row["name"],
            "spotify_uris": json.loads(row["spotify_uris"]),
            "palette": row["palette"],
        }

    def put(self, name: str, spotify_uris: list[str], palette: str | None) -> dict[str, Any]:
        if not _key(name):
            raise ValueError("playlist name is empty")
        if palette is not None and palette not in PALETTES:
            raise UnknownPalette(palette)
        self.con.execute(
            "INSERT OR REPLACE INTO playlists VALUES (?, ?, ?, ?)",
            (_key(name), name, json.dumps([str(u) for u in spotify_uris]), palette),
        )
        self.con.commit()
        return self.get(name)

    def get(self, name: str) -> dict[str, Any]:
        row = self.con.execute("SELECT * FROM playlists WHERE key = ?", (_key(name),)).fetchone()
        if row is None:
            raise UnknownPlaylist(name)
        return self._row(row)

    def list(self) -> list[dict[str, Any]]:
        return [self._row(r) for r in self.con.execute("SELECT * FROM playlists ORDER BY key")]

    def delete(self, name: str) -> None:
        if self.con.execute("DELETE FROM playlists WHERE key = ?", (_key(name),)).rowcount == 0:
            raise UnknownPlaylist(name)
        self.con.commit()

    def match(self, query: str) -> dict[str, Any] | None:
        """The playlist a spoken query names ("prism chill", "the chill
        playlist", "prison chill"), or None. Filler words and "prism" are
        ignored on both sides."""
        q_core, q_full = _core(query), _key(query)
        if not q_core:
            return None
        best: tuple[float, dict[str, Any]] | None = None
        for p in self.list():
            # Full names too, so a misheard "prism" ("prison chill") still lands.
            score = max(
                SequenceMatcher(None, q_core, _core(p["name"]) or _key(p["name"])).ratio(),
                SequenceMatcher(None, q_full, _key(p["name"])).ratio(),
            )
            if best is None or score > best[0]:
                best = (score, p)
        return best[1] if best is not None and best[0] >= MATCH_THRESHOLD else None

    def close(self) -> None:
        self.con.close()


def _uri_to_show(requests: RequestStore, shows: ShowStore) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in requests.list():
        uri = (r.get("external") or {}).get("spotify_uri")
        if uri and r["status"] == "published" and r["show_id"] and shows.exists(r["show_id"]):
            out[str(uri)] = str(r["show_id"])
    return out


def show_ids(playlist: dict[str, Any], requests: RequestStore, shows: ShowStore) -> list[str]:
    """The playlist's playable shows, in playlist order."""
    by_uri = _uri_to_show(requests, shows)
    ids = [by_uri[u] for u in playlist["spotify_uris"] if u in by_uri]
    return list(dict.fromkeys(ids))


def palette_for(
    show_id: str, playlists: PlaylistStore, requests: RequestStore, shows: ShowStore
) -> str | None:
    """The palette of the first playlist (by name) holding this show's song."""
    uris = {u for u, s in _uri_to_show(requests, shows).items() if s == show_id}
    if not uris:
        return None
    for p in playlists.list():
        if p["palette"] and uris & set(p["spotify_uris"]):
            return str(p["palette"])
    return None
