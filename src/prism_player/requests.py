"""Requests: the queue of songs a companion client should analyze, in SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUSES = ("open", "analyzing", "published", "rejected")


class UnknownRequest(KeyError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class RequestStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                external TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                status TEXT NOT NULL,
                show_id TEXT
            )"""
        )
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS request_external (
                value TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE
            )"""
        )
        self.con.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "artist": row["artist"],
            "external": json.loads(row["external"]),
            "requested_at": row["requested_at"],
            "status": row["status"],
            "show_id": row["show_id"],
        }

    def create(
        self, title: str, artist: str, external: dict[str, Any] | None
    ) -> tuple[dict[str, Any], bool]:
        """Insert a request, or return the existing one sharing any external id.

        Returns (request, created).
        """
        external = external or {}
        values = [str(v) for v in external.values() if v]
        for value in values:
            row = self.con.execute(
                "SELECT r.* FROM requests r JOIN request_external e ON e.request_id = r.id"
                " WHERE e.value = ?",
                (value,),
            ).fetchone()
            if row:
                return self._row(row), False
        request_id = uuid.uuid4().hex
        self.con.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?, 'open', NULL)",
            (request_id, title, artist, json.dumps(external), _now()),
        )
        self.con.executemany(
            "INSERT OR IGNORE INTO request_external VALUES (?, ?)",
            [(value, request_id) for value in values],
        )
        self.con.commit()
        return self.get(request_id), True

    def get(self, request_id: str) -> dict[str, Any]:
        row = self.con.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise UnknownRequest(request_id)
        return self._row(row)

    def list(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM requests ORDER BY requested_at DESC, rowid DESC"
        ).fetchall()
        return [self._row(r) for r in rows]

    def update(self, request_id: str, status: str, show_id: str | None) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        current = self.get(request_id)
        self.con.execute(
            "UPDATE requests SET status = ?, show_id = ? WHERE id = ?",
            (status, show_id if show_id is not None else current["show_id"], request_id),
        )
        self.con.commit()
        return self.get(request_id)

    def close(self) -> None:
        self.con.close()
