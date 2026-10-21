"""Testy dlouhodobé paměti."""

from __future__ import annotations

import json

import pytest

from martin.memory.manager import MemoryManager
from martin.memory.store import CATEGORIES, MemoryStore


class TestMemoryStore:
    def test_remember_and_count(self, memory_store):
        entry = memory_store.remember("Lukas ma rád MSFS", "projekt")
        assert entry.id > 0
        assert memory_store.count() == 1
        assert entry.content == "Lukas ma rád MSFS"
        assert entry.category == "projekt"

    def test_empty_content_is_rejected(self, memory_store):
        with pytest.raises(ValueError):
            memory_store.remember("   ")

    def test_unknown_category_falls_back(self, memory_store):
        entry = memory_store.remember("x", "neexistujici")
        assert entry.category == "jine"
        assert entry.category in CATEGORIES

    def test_search_finds_czech_diacritics(self, memory_store):
        memory_store.remember("Preferuje temny motiv", "preference")
        results = memory_store.search("temy motiv")
        assert len(results) == 1
        assert "motiv" in results[0].content

    def test_search_is_limited(self, memory_store):
        for i in range(30):
            memory_store.remember(f"testovaci zaznam {i}", "jine")
        results = memory_store.search("testovaci", limit=5)
        assert len(results) == 5

    def test_search_empty_query_lists(self, memory_store):
        memory_store.remember("a", "jine")
        assert len(memory_store.search("")) == 1

    def test_update_changes_content(self, memory_store):
        entry = memory_store.remember("puvodni", "jine")
        updated = memory_store.update(entry.id, content="nove")
        assert updated is not None
        assert updated.content == "nove"

    def test_update_ignores_unknown_fields(self, memory_store):
        entry = memory_store.remember("puvodni", "jine")
        updated = memory_store.update(entry.id, evil_field="x")
        assert updated is not None
        assert updated.content == "puvodni"

    def test_delete_removes_entry(self, memory_store):
        entry = memory_store.remember("k odstraneni", "jine")
        assert memory_store.delete(entry.id) is True
        assert memory_store.count() == 0

    def test_delete_missing_returns_false(self, memory_store):
        assert memory_store.delete(9999) is False

    def test_pinned_sorts_first(self, memory_store):
        memory_store.remember("normalni", "jine")
        pinned = memory_store.remember("pivnuty", "jine", pinned=True)
        entries = memory_store.list()
        assert entries[0].id == pinned.id

    def test_export_and_import(self, memory_store, temp_dir):
        memory_store.remember("exportovana vzpominka", "projekt")
        path = memory_store.export(temp_dir / "export.json")
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["count"] == 1
        assert data["memories"][0]["content"] == "exportovana vzpominka"

    def test_import_entries(self, memory_store):
        count = memory_store.import_entries(
            [{"content": "z importu", "category": "jine"}, {"content": ""}]
        )
        assert count == 1
        assert memory_store.count() == 1

    def test_clear_removes_all(self, memory_store):
        for i in range(5):
            memory_store.remember(f"zaznam {i}", "jine")
        assert memory_store.clear() == 5
        assert memory_store.count() == 0


class TestMemoryManager:
    def test_context_for_builds_prompt_context(self, memory_store):
        manager = MemoryManager(memory_store)
        manager.remember("Lukas pouziva MSFS 2024", "projekt")
        context = manager.context_for("co hraju")
        assert "MSFS 2024" in context
        assert "paměti" in context.lower()

    def test_context_falls_back_to_recent_when_no_match(self, memory_store):
        """Bez textove shody se pouzije poslednich nekolik zaznamu."""
        manager = MemoryManager(memory_store)
        manager.remember("něco o rybách", "jine")
        context = manager.context_for("letadlo")
        assert "rybách" in context

    def test_context_empty_when_memory_is_empty(self, memory_store):
        manager = MemoryManager(memory_store)
        assert manager.context_for("cokoliv") == ""

    def test_context_prefers_pinned_entries(self, memory_store):
        manager = MemoryManager(memory_store)
        manager.remember("běžný záznam", "jine")
        manager.remember("připnutý záznam", "jine", source="user")
        entries = manager.store.list(limit=10)
        pinned_id = entries[0].id
        manager.store.update(pinned_id, pinned=True)
        context = manager.context_for("cokoliv")
        assert "připnutý" in context

    def test_remember_returns_dict(self, memory_store):
        manager = MemoryManager(memory_store)
        result = manager.remember("nová vzpomínka", "preference")
        assert result["content"] == "nová vzpomínka"
        assert result["category"] == "preference"

    def test_invalid_category_normalized(self, memory_store):
        manager = MemoryManager(memory_store)
        result = manager.remember("x", "nesmysl")
        assert result["category"] == "jine"