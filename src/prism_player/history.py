"""Recently played shows, so a shuffle feels fresh.

A plain shuffle of a short playlist often opens with a song that just
played. `fresh_shuffle` shuffles, then moves recently played shows to the
end, most recent last: songs not heard lately come first, and a playlist
restart never opens with the song heard most recently. The list persists in
the data dir so restarts keep it.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

log = logging.getLogger("prism_player.history")

KEEP = 200


class PlayHistory:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.recent: list[str] = []
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text())
                self.recent = [str(s) for s in data][-KEEP:]
            except (OSError, ValueError):
                log.warning("unreadable play history at %s; starting empty", path)

    def record(self, show_id: str) -> None:
        if show_id in self.recent:
            self.recent.remove(show_id)
        self.recent.append(show_id)
        del self.recent[:-KEEP]
        if self.path is not None:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.recent))
            tmp.replace(self.path)

    def fresh_shuffle(self, ids: list[str], rng: random.Random | None = None) -> list[str]:
        out = list(ids)
        (rng or random).shuffle(out)
        rank = {s: i for i, s in enumerate(self.recent)}
        # Stable sort keeps the shuffle among shows with equal rank (never
        # played, rank -1); played shows go last, oldest play first.
        out.sort(key=lambda s: rank.get(s, -1))
        return out
