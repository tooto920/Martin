"""Stránka bezpečnosti - historie rozhodnutí a seznam nástrojů."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from martin.ui.theme import get_theme

OUTCOME_LABELS = {
    "allow": "Povoleno",
    "confirm_required": "Vyžaduje potvrzení",
    "deny": "Zablokováno",
    "error": "Chyba",
}


class SecurityPage(QWidget):
    """Historie bezpečnostních rozhodnutí."""

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
        self._filter = QComboBox()
        self._filter.addItem("Vše", "")
        for key, label in OUTCOME_LABELS.items():
            self._filter.addItem(label, key)
        self._refresh_btn = QPushButton("Obnovit")
        self._clear_btn = QPushButton("Vymazat historii")
        header.addWidget(QLabel("Filtrovat:"))
        header.addWidget(self._filter)
        header.addStretch(1)
        header.addWidget(self._refresh_btn)
        header.addWidget(self._clear_btn)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self._events = QListWidget()
        splitter.addWidget(self._events)

        tools_box = QFrame()
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_title = QLabel("Registrované nástroje")
        tools_title.setObjectName("Title")
        tools_layout.addWidget(tools_title)
        self._tools = QListWidget()
        tools_layout.addWidget(self._tools)
        splitter.addWidget(tools_box)
        splitter.setSizes([340, 220])

        layout.addWidget(splitter, 1)
        self._status = QLabel("")
        self._status.setObjectName("Subtitle")
        layout.addWidget(self._status)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _connect(self) -> None:
        self._filter.currentIndexChanged.connect(self._refresh)
        self._refresh_btn.clicked.connect(self._refresh)
        self._clear_btn.clicked.connect(self._clear)
        self._ctx.security_event.connect(self._refresh)

    def _refresh(self) -> None:
        self._events.clear()
        outcome = self._filter.currentData() or None
        events = self._ctx.audit_log.events()
        shown = 0
        for event in reversed(events):
            if outcome and event.outcome != outcome:
                continue
            label = OUTCOME_LABELS.get(event.outcome, event.outcome)
            args = ", ".join(f"{k}={v}" for k, v in (event.args or {}).items())
            text = (
                f"{event.timestamp[11:19]}  [{label}]  {event.tool}"
                + (f"  ({args})" if args else "")
            )
            item = QListWidgetItem(text)
            if event.outcome == "deny":
                item.setForeground(Qt.GlobalColor.red)
            elif event.outcome == "confirm_required":
                item.setForeground(Qt.GlobalColor.darkYellow)
            self._events.addItem(item)
            shown += 1
        self._status.setText(f"Zobrazeno {shown} událostí.")

        self._tools.clear()
        for spec in self._ctx.policy.describe():
            level = spec["level"].upper()
            item = QListWidgetItem(f"[{level}] {spec['name']} - {spec['description']}")
            self._tools.addItem(item)

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self,
            "Vymazat historii?",
            "Opravdu chceš smazat celou historii bezpečnostních událostí?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._ctx.clear_audit_log()
        self._refresh()

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)