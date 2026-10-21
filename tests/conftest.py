"""Sdílené fixture pro testy Martina."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def temp_dir():
    """Dočasný adresář pro testy."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture()
def settings_store(temp_dir):
    """Izolované úložiště nastavení."""
    from martin.core.settings import SettingsStore

    return SettingsStore(temp_dir / "settings.json")


@pytest.fixture()
def audit_log(temp_dir):
    """Auditní log v dočasném adresáři."""
    from martin.security.audit import AuditLog

    return AuditLog(temp_dir / "security.jsonl")


@pytest.fixture()
def registry():
    """Prázdný registr nástrojů."""
    from martin.security.engine import ToolRegistry

    return ToolRegistry()


@pytest.fixture()
def policy(registry, audit_log):
    """Policy engine s prázdným registrem."""
    from martin.security.engine import PolicyEngine

    return PolicyEngine(registry, audit_log)


@pytest.fixture()
def memory_store(temp_dir):
    """Izolovaná databáze paměti."""
    from martin.memory.store import MemoryStore

    store = MemoryStore(temp_dir / "memory.db")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture()
def app_registry():
    """Registr aplikací (bez skutečného spouštění)."""
    from martin.system.apps import AppRegistry

    return AppRegistry()