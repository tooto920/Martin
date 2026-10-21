"""Historie konverzací."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from martin.ui.theme import get_theme


class HistoryPage(QWidget):
    """Prohlížení uložených konverzací."""

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

        self._list = QListWidget()
        self._list.setMaximumHeight(200)
        layout.addWidget(self._list)

        self._viewer = QTextBrowser()
        layout.addWidget(self._viewer, 1)

        buttons = QHBoxLayout()
        self._rename_btn = QPushButton("Přejmenovat")
        self._delete_btn = QPushButton("Smazat")
        self._load_btn = QPushButton("Načíst do chatu")
        buttons.addWidget(self._rename_btn)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._load_btn)
        layout.addLayout(buttons)

        self._status = QLabel("")
        self._status.setObjectName("Subtitle")
        layout.addWidget(self._status)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _connect(self) -> None:
        self._list.currentItemChanged.connect(self._on_select)
        self._rename_btn.clicked.connect(self._rename)
        self._delete_btn.clicked.connect(self._delete)
        self._load_btn.clicked.connect(self._load_into_chat)

    def refresh(self) -> None:
        """Načte seznam konverzací."""
        self._list.clear()
        for conversation in self._ctx.conversations.list_conversations():
            item = QListWidgetItem(
                f"{conversation.updated_at[5:16].replace('T', ' ')}  "
                f"{conversation.title}  ({conversation.message_count})"
            )
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            self._list.addItem(item)

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _on_select(self, current: Any, _previous: Any) -> None:
        conversation_id = self._selected_id()
        if conversation_id is None:
            return
        messages = self._ctx.conversations.get_messages(conversation_id)
        parts = []
        for message in messages:
            who = "Martin" if message["role"] == "assistant" else "Ty"
            parts.append(f"<b>{who}:</b><br>{message['content']}")
        self._viewer.setHtml("<br><br>".join(parts))

    def _rename(self) -> None:
        conversation_id = self._selected_id()
        if conversation_id is None:
            return
        title, ok = QInputDialog.getText(
            self, "Přejmenovat konverzaci", "Nový název:"
        )
        if ok and title.strip():
            self._ctx.conversations.rename(conversation_id, title.strip())
            self.refresh()

    def _delete(self) -> None:
        conversation_id = self._selected_id()
        if conversation_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Smazat konverzaci?",
            "Opravdu chceš tuto konverzaci smazat?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._ctx.conversations.delete(conversation_id)
            self.refresh()

    def _load_into_chat(self) -> None:
        conversation_id = self._selected_id()
        if conversation_id is None:
            self._status.setText("Nejprve vyber konverzaci.")
            return
        self._ctx.load_conversation(conversation_id)
        self._status.setText("Konverzace načtena do chatu.")

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)