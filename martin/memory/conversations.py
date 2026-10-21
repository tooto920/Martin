"""Historie konverzací v SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Conversation:
    """Jedna uložená konverzace."""

    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "model": self.model,
        }


class ConversationStore:
    """Ukládání a načítání konverzací a zpráv."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _session(self):
        """Kontext, ktery po skonceni VZDY zavre pripojeni.

        `with sqlite3.connect(...)` totiz neprovede zavreni - spojeni
        zustava otevrene, coz na Windows drzi soubor zamceny.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """Zavre pripojeni a sjednoti WAL soubory."""
        try:
            with self._session() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

    def _init_db(self) -> None:
        with self._lock, self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    title        TEXT NOT NULL DEFAULT 'Nová konverzace',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    model        TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role            TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id);
                """
            )

    def create(self, title: str = "Nová konverzace", model: str = "") -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._session() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (title, created_at, updated_at, model)"
                " VALUES (?, ?, ?, ?)",
                (title, now, now, model),
            )
            return int(cursor.lastrowid or 0)

    def add_message(self, conversation_id: int, role: str, content: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._session() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at)"
                " VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            return int(cursor.lastrowid or 0)

    def get_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        with self._lock, self._session() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages"
                " WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_conversations(self, limit: int = 100) -> list[Conversation]:
        with self._lock, self._session() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at, c.model,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)
                           AS message_count
                FROM conversations c
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [
            Conversation(
                id=int(r["id"]),
                title=r["title"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                message_count=int(r["message_count"]),
                model=r["model"] or "",
            )
            for r in rows
        ]

    def rename(self, conversation_id: int, title: str) -> bool:
        with self._lock, self._session() as conn:
            cursor = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, datetime.now().isoformat(timespec="seconds"), conversation_id),
            )
            return cursor.rowcount > 0

    def delete(self, conversation_id: int) -> bool:
        with self._lock, self._session() as conn:
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            cursor = conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            return cursor.rowcount > 0

    def export(self, path: Path | str) -> Path:
        """Exportuje všechny konverzace do JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        conversations = []
        for conv in self.list_conversations(limit=10000):
            data = conv.to_dict()
            data["messages"] = self.get_messages(conv.id)
            conversations.append(data)
        target.write_text(
            json.dumps(
                {"exported_at": datetime.now().isoformat(timespec="seconds"),
                 "conversations": conversations},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return target