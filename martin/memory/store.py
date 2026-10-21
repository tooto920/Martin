"""Úložiště dlouhodobé paměti nad SQLite.

Schema:
  memories(id, content, category, created_at, updated_at, pinned, source)

Vyhledávání používá FTS5 (pokud je dostupný) s fallbackem na LIKE.
Celá databáze se NIKDY nenačítá do kontextu - vždy se dotazuje
přes relevantní výběr.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CATEGORIES = ("preference", "aplikace", "projekt", "osobni", "jine")


@dataclass(slots=True)
class MemoryEntry:
    """Jeden záznam v paměti."""

    id: int
    content: str
    category: str
    created_at: str
    updated_at: str
    pinned: bool
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pinned": self.pinned,
            "source": self.source,
        }


class MemoryStore:
    """SQLite úložiště paměti s vláknovou bezpečností."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fts_enabled = False
        self._init_db()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _init_db(self) -> None:
        with self._lock, self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    content    TEXT NOT NULL,
                    category   TEXT NOT NULL DEFAULT 'jine',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pinned     INTEGER NOT NULL DEFAULT 0,
                    source     TEXT NOT NULL DEFAULT 'user'
                );
                CREATE INDEX IF NOT EXISTS idx_memories_category
                    ON memories(category);
                CREATE INDEX IF NOT EXISTS idx_memories_pinned
                    ON memories(pinned);
                """
            )
            try:
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(content, content='memories', content_rowid='id');
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content)
                        VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                        INSERT INTO memories_fts(rowid, content)
                        VALUES (new.id, new.content);
                    END;
                    """
                )
                self._fts_enabled = True
            except sqlite3.OperationalError:
                # FTS5 není v dané sestavě k dispozici - použijeme LIKE.
                self._fts_enabled = False

    @property
    def fts_enabled(self) -> bool:
        return self._fts_enabled

    # -- CRUD -----------------------------------------------------------
    def remember(
        self,
        content: str,
        category: str = "jine",
        source: str = "user",
        pinned: bool = False,
    ) -> MemoryEntry:
        """Uloží nový záznam do paměti."""
        content = content.strip()
        if not content:
            raise ValueError("Obsah paměti nesmí být prázdný.")
        if category not in CATEGORIES:
            category = "jine"
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._session() as conn:
            cursor = conn.execute(
                "INSERT INTO memories (content, category, created_at, updated_at, pinned, source)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (content, category, now, now, int(pinned), source),
            )
            entry_id = int(cursor.lastrowid or 0)
        return self.get(entry_id)

    def get(self, entry_id: int) -> MemoryEntry:
        """Načte jeden záznam."""
        with self._lock, self._session() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (entry_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Záznam paměti {entry_id} neexistuje.")
        return _row_to_entry(row)

    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Vyhledá záznamy relevantní k dotazu.

        Vrací omezený počet záznamů - nikdy celou databázi.

        FTS5 v české podobě nerozpoznává varianty (např. "hraju" vs.
        "hraje"), proto se po přesném FTS dotazu doplňuje ještě
        libovolný (LIKE) výsledek. Dotaz se navíc rozloží na jednotlivá
        slova, aby se hledalo i části věty.
        """
        query = (query or "").strip()
        if not query:
            return self.list(limit=limit)
        limit = max(1, min(int(limit), 100))
        with self._lock, self._session() as conn:
            rows: list[sqlite3.Row] = []
            seen: set[int] = set()

            if self._fts_enabled:
                try:
                    match = _fts_query(query)
                    for row in conn.execute(
                        """
                        SELECT m.* FROM memories_fts f
                        JOIN memories m ON m.id = f.rowid
                        WHERE memories_fts MATCH ?
                        ORDER BY bm25(memories_fts), m.pinned DESC
                        LIMIT ?
                        """,
                        (match, limit),
                    ).fetchall():
                        seen.add(int(row["id"]))
                        rows.append(row)
                except sqlite3.OperationalError:
                    pass

            # Doplnění: hledání po jednotlivých slovech dotazu.
            for token in _tokens(query):
                if len(rows) >= limit:
                    break
                for row in self._like_search(conn, token, limit):
                    if int(row["id"]) not in seen:
                        seen.add(int(row["id"]))
                        rows.append(row)

            if not rows:
                rows = self._like_search(conn, query, limit)

        rows = rows[:limit]
        return [_row_to_entry(row) for row in rows]

    @staticmethod
    def _like_search(
        conn: sqlite3.Connection, query: str, limit: int
    ) -> list[sqlite3.Row]:
        pattern = f"%{query}%"
        return conn.execute(
            """
            SELECT * FROM memories
            WHERE content LIKE ? OR category LIKE ?
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()

    def list(
        self,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryEntry]:
        """Vypíše záznamy (nejnovější první)."""
        limit = max(1, min(int(limit), 1000))
        with self._lock, self._session() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE category = ?"
                    " ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?",
                    (category, limit, int(offset)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories"
                    " ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?",
                    (limit, int(offset)),
                ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def update(self, entry_id: int, **changes: Any) -> MemoryEntry | None:
        """Upraví záznam. Vrací nový stav nebo None."""
        allowed = {"content", "category", "pinned"}
        sets: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "category" and value not in CATEGORIES:
                continue
            if key == "pinned":
                value = int(bool(value))
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get(entry_id)
        sets.append("updated_at = ?")
        values.append(datetime.now().isoformat(timespec="seconds"))
        values.append(entry_id)
        with self._lock, self._session() as conn:
            conn.execute(
                f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", values
            )
        try:
            return self.get(entry_id)
        except KeyError:
            return None

    def delete(self, entry_id: int) -> bool:
        """Smaže záznam. Vrací True, pokud byl smazán."""
        with self._lock, self._session() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    def count(self) -> int:
        with self._lock, self._session() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()
            return int(row["c"]) if row else 0

    def clear(self) -> int:
        """Smaže všechny záznamy. Vrací počet smazaných."""
        with self._lock, self._session() as conn:
            cursor = conn.execute("DELETE FROM memories")
            return int(cursor.rowcount)

    def export(self, path: Path | str) -> Path:
        """Exportuje paměť do JSON souboru."""
        import json

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        entries = self.list(limit=100000)
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(entries),
            "memories": [e.to_dict() for e in entries],
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return target

    def import_entries(self, entries: list[dict[str, Any]]) -> int:
        """Importuje záznamy z exportu. Vrací počet importovaných."""
        imported = 0
        for item in entries:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            category = str(item.get("category", "jine"))
            source = str(item.get("source", "import"))
            try:
                self.remember(content, category, source, bool(item.get("pinned")))
                imported += 1
            except ValueError:
                continue
        return imported


def _tokens(query: str) -> list[str]:
    """Rozloží dotaz na jednotlivá slova delší než 2 znaky."""
    words = [
        w
        for w in "".join(c if c.isalnum() else " " for c in query).split()
        if len(w) > 2
    ]
    return list(dict.fromkeys(words))


def _fts_query(query: str) -> str:
    """Sestaví bezpečný FTS5 dotaz z uživatelského vstupu."""
    tokens = [
        t for t in "".join(c if c.isalnum() else " " for c in query).split() if t
    ]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens)


def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=int(row["id"]),
        content=row["content"],
        category=row["category"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        pinned=bool(row["pinned"]),
        source=row["source"],
    )