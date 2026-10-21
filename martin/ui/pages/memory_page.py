"""Správa dlouhodobé paměti - vyhledávání, úpravy, export, mazání."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from martin.ui.theme import get_theme

CATEGORY_LABELS = {
    "preference": "Preference",
    "aplikace": "Aplikace",
    "projekt": "Projekt",
    "osobni": "Osobní",
    "jine": "Jiné",
}


class MemoryPage(QWidget):
    """Stránka pro správu paměti."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx
        self._theme = get_theme(ctx.settings.theme)
        self._build()
        self._connect()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Hledat v paměti...")
        self._category = QComboBox()
        self._category.addItem("Vše", "")
        for key, label in CATEGORY_LABELS.items():
            self._category.addItem(label, key)
        header.addWidget(self._search, 1)
        header.addWidget(self._category)
        layout.addLayout(header)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        self._add_btn = QPushButton("Přidat")
        self._edit_btn = QPushButton("Upravit")
        self._delete_btn = QPushButton("Smazat")
        self._export_btn = QPushButton("Exportovat")
        self._import_btn = QPushButton("Importovat")
        self._clear_btn = QPushButton("Smazat vše")
        for button in (
            self._add_btn,
            self._edit_btn,
            self._delete_btn,
            self._export_btn,
            self._import_btn,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self._clear_btn)
        layout.addLayout(buttons)

        self._status = QLabel("")
        self._status.setObjectName("Subtitle")
        layout.addWidget(self._status)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _connect(self) -> None:
        self._search.textChanged.connect(self._refresh)
        self._category.currentIndexChanged.connect(self._refresh)
        self._add_btn.clicked.connect(self._add)
        self._edit_btn.clicked.connect(self._edit)
        self._delete_btn.clicked.connect(self._delete)
        self._export_btn.clicked.connect(self._export)
        self._import_btn.clicked.connect(self._import)
        self._clear_btn.clicked.connect(self._clear)
        self._ctx.memory_changed.connect(self._refresh)

    # --- akce -----------------------------------------------------------
    def _refresh(self) -> None:
        self._list.clear()
        query = self._search.text().strip()
        category = self._category.currentData() or None
        try:
            if query:
                entries = self._ctx.memory_manager.search(query, limit=100)
            elif category:
                entries = self._ctx.memory_manager.list_all(category, limit=200)
            else:
                entries = self._ctx.memory_manager.list_all(None, limit=200)
        except Exception as exc:  # noqa: BLE001
            self._status.setText(f"Chyba při čtení paměti: {exc}")
            return
        for entry in entries:
            label = CATEGORY_LABELS.get(entry["category"], entry["category"])
            pin = "📌 " if entry.get("pinned") else ""
            item = QListWidgetItem(f"{pin}[{label}] {entry['content']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self._list.addItem(item)
        self._status.setText(f"Nalezeno {len(entries)} záznamů.")

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _add(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Nová vzpomínka", "Co si má Martin pamatovat?"
        )
        if not ok or not text.strip():
            return
        category = self._category.currentData() or "jine"
        self._ctx.memory_manager.remember(text.strip(), category, "user")
        self._ctx.emit_memory_changed()
        self._status.setText("Záznam uložen.")

    def _edit(self) -> None:
        entry_id = self._selected_id()
        if entry_id is None:
            self._status.setText("Nejprve vyber záznam.")
            return
        entries = self._ctx.memory_manager.list_all(None, limit=1000)
        current = next((e for e in entries if e["id"] == entry_id), None)
        if current is None:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Upravit vzpomínku", "Obsah:", current["content"]
        )
        if not ok:
            return
        self._ctx.memory_manager.update(entry_id, content=text.strip())
        self._ctx.emit_memory_changed()
        self._status.setText("Záznam upraven.")

    def _delete(self) -> None:
        entry_id = self._selected_id()
        if entry_id is None:
            self._status.setText("Nejprve vyber záznam.")
            return
        self._ctx.memory_manager.delete(entry_id)
        self._ctx.emit_memory_changed()
        self._status.setText("Záznam smazán.")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportovat paměť", "martin_pamat.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            self._ctx.memory_manager.export(path)
            self._status.setText(f"Paměť exportována do {path}")
        except OSError as exc:
            self._status.setText(f"Export selhal: {exc}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importovat paměť", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(open(path, encoding="utf-8").read())
            count = self._ctx.memory_manager.import_entries(data.get("memories", []))
            self._ctx.emit_memory_changed()
            self._status.setText(f"Importováno {count} záznamů.")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._status.setText(f"Import selhal: {exc}")

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self,
            "Smazat celou paměť?",
            "Opravdu chceš smazat všechny záznamy z paměti?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._ctx.memory_manager.store.clear()
        self._ctx.emit_memory_changed()
        self._status.setText("Paměť vyprázdněna.")

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)