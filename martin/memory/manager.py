"""Vrstva nad MemoryStore - dává nástrojům jednoduché API."""

from __future__ import annotations

from typing import Any

from martin.memory.store import CATEGORIES, MemoryStore


class MemoryManager:
    """Obal nad MemoryStore pro použití z nástrojů a UI."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def store(self) -> MemoryStore:
        return self._store

    def remember(
        self, content: str, category: str = "jine", source: str = "assistant"
    ) -> dict[str, Any]:
        """Uloží informaci do paměti."""
        if category not in CATEGORIES:
            category = "jine"
        entry = self._store.remember(content, category, source)
        return entry.to_dict()

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Vyhledá relevantní vzpomínky."""
        return [e.to_dict() for e in self._store.search(query, limit=limit)]

    def context_for(self, query: str, limit: int = 6) -> str:
        """Sestaví textový kontext z relevantních vzpomínek pro LLM.

        Kontext je vždy OMEZENÝ - nikdy se do něj nenačítá celá
        databáze. Sestává se z:
          1. vzpomínek nalezených fulltextovým vyhledáváním,
          2. připnutých vzpomínek (uživatel označil jako důležité),
          3. pokud nic nenalezeno, z posledních několika záznamů.

        Bod 3 slouží jako rozumná záloha pro dotazy, které nemají
        společná slova se záznamy (např. "co hraju" vs. "MSFS 2024").
        """
        entries = list(self._store.search(query, limit=limit))
        seen = {e.id for e in entries}

        # Připnuté vzpomínky jsou důležité vždy.
        for entry in self._store.list(limit=limit * 2):
            if entry.pinned and entry.id not in seen:
                seen.add(entry.id)
                entries.append(entry)

        # Záloha: poslední záznamy, pokud dosud nic relevantního.
        if not entries:
            for entry in self._store.list(limit=3):
                if entry.id not in seen:
                    seen.add(entry.id)
                    entries.append(entry)

        if not entries:
            return ""
        lines = [f"- [{e.category}] {e.content}" for e in entries[:limit]]
        return "Relevantní informace z paměti uživatele:\n" + "\n".join(lines)

    def list_all(
        self, category: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._store.list(category=category, limit=limit)]

    def update(self, entry_id: int, **changes: Any) -> dict[str, Any] | None:
        entry = self._store.update(entry_id, **changes)
        return entry.to_dict() if entry else None

    def delete(self, entry_id: int) -> bool:
        return self._store.delete(entry_id)

    def count(self) -> int:
        return self._store.count()

    def export(self, path: str) -> str:
        return str(self._store.export(path))

    def import_entries(self, entries: list[dict[str, Any]]) -> int:
        return self._store.import_entries(entries)