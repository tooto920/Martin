"""Chatové okno - zprávy, vstup, stav modelu a hlasu."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from martin.ui.animated import AnimatedButton, PulseIndicator
from martin.ui.theme import Theme, get_theme


class MessageBubble(QFrame):
    """Jedna zpráva v chatu - bublinka s textem a metadaty."""

    def __init__(self, role: str, text: str = "", theme: Theme | None = None) -> None:
        super().__init__()
        self._role = role
        self._theme = theme or get_theme("dark")
        self.setObjectName("Bubble")
        self._build(text)

    def _build(self, text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        header = QLabel("Martin" if self._role == "assistant" else "Ty")
        header.setObjectName("Subtitle")
        layout.addWidget(header)

        self._body = QLabel(text)
        self._body.setTextFormat(
            Qt.TextFormat.MarkdownText if self._role == "assistant" else Qt.TextFormat.PlainText
        )
        self._text = text
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(self._body)

        self._footer = QLabel("")
        self._footer.setObjectName("Subtitle")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._footer)
        self.apply_theme(self._theme)

    def set_text(self, text: str) -> None:
        self._text = text
        self._body.setText(text)

    def append_text(self, text: str) -> None:
        self.set_text(self._text + text)

    def set_footer(self, text: str) -> None:
        self._footer.setText(text)

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        if self._role == "user":
            bg, border, text_color = theme.user_bubble, theme.accent, theme.text
        else:
            bg, border, text_color = theme.assistant_bubble, theme.border, theme.text
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; border: none; color: {text_color}; }}
            """
        )


class ChatView(QWidget):
    """Hlavní chatová plocha."""

    message_submitted = Signal(str)
    stop_requested = Signal()
    screenshot_requested = Signal()
    mic_toggled = Signal()

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx
        self._theme = get_theme(ctx.settings.theme)
        self._streaming = False
        self._reply: MessageBubble | None = None
        self._build()
        self._connect()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._messages = QVBoxLayout(self._content)
        self._messages.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._messages.setSpacing(9)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

        root.addWidget(self._build_input())

    def _build_input(self) -> QWidget:
        box = QFrame()
        box.setObjectName("InputBox")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self._mic = PulseIndicator("#3fb950")
        self._mic.setToolTip("Stav mikrofonu")
        layout.addWidget(self._mic)
        self._mic_button = QPushButton("Mikrofon")
        self._mic_button.setToolTip("Zapnout / vypnout mikrofon (Ctrl+Shift+Mezerník)")
        self._mic_button.clicked.connect(self.mic_toggled.emit)
        layout.addWidget(self._mic_button)

        self._input = QTextEdit()
        self._input.setPlaceholderText(
            "Napiš Martinovi zprávu... (Enter odesílá, Shift+Enter nový řádek)"
        )
        self._input.setFixedHeight(46)
        self._input.installEventFilter(self)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._input, 1)

        self._shot_button = QPushButton("👁")
        self._shot_button.setToolTip("Co je na obrazovce?")
        self._shot_button.setFixedSize(38, 38)
        self._shot_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._shot_button)

        self._send = AnimatedButton("Odeslat")
        self._send.setFixedSize(92, 38)
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._send)

        self._stop = QPushButton("⏹")
        self._stop.setToolTip("Zastavit")
        self._stop.setFixedSize(38, 38)
        self._stop.setVisible(False)
        self._stop.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._stop)

        self._input.textChanged.connect(self._on_text_changed)
        self._send.clicked.connect(self._submit)
        self._stop.clicked.connect(self.stop_requested.emit)
        self._shot_button.clicked.connect(self.screenshot_requested.emit)
        return box

    def _connect(self) -> None:
        self._ctx.stream_started.connect(self._on_stream_started)
        self._ctx.stream_chunk.connect(self._on_stream_chunk)
        self._ctx.stream_finished.connect(self._on_stream_finished)
        self._ctx.error_occurred.connect(self._on_error)
        self._ctx.listening_changed.connect(self._on_listening)
        self._ctx.speaking_changed.connect(self._on_speaking)

    # -- akce -----------------------------------------------------------
    def _on_text_changed(self) -> None:
        self._send.setEnabled(not self._streaming and bool(self._input.toPlainText().strip()))

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._submit()
                return True
        return super().eventFilter(obj, event)

    def _submit(self) -> None:
        text = self._input.toPlainText().strip()
        busy = getattr(self._ctx, "_busy", None)
        if not text or self._streaming or (busy is not None and busy.is_set()):
            return
        self._input.clear()
        self.message_submitted.emit(text)

    def add_message(self, role: str, text: str) -> MessageBubble:
        """Přidá bublinku do chatu."""
        bubble = MessageBubble(role, text, self._theme)
        self._messages.addWidget(bubble)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())
        return bubble

    def _on_stream_started(self) -> None:
        self._streaming = True
        self._reply = self.add_message("assistant", "")
        self._stop.setVisible(True)
        self._send.setEnabled(False)

    def _on_stream_chunk(self, text: str) -> None:
        if self._reply is None:
            self._reply = self.add_message("assistant", "")
        if self._reply is not None:
            self._reply.append_text(text)
            self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

    def _on_stream_finished(self, info: str = "") -> None:
        self._streaming = False
        self._stop.setVisible(False)
        self._send.setEnabled(bool(self._input.toPlainText().strip()))
        if self._reply is not None:
            self._reply.set_footer(info or time.strftime("%H:%M"))
        self._reply = None

    def _on_error(self, message: str) -> None:
        self._streaming = False
        self.add_message("assistant", f"⚠️ {message}")
        self._stop.setVisible(False)
        self._send.setEnabled(True)

    def _on_listening(self, active: bool) -> None:
        self._mic_button.setText("Dokončit" if active else "Mikrofon")
        self._mic.set_active(active)
        self._mic.set_color("#f85149" if active else "#3fb950")

    def _on_speaking(self, active: bool) -> None:
        if active:
            self._mic.set_active(True)
            self._mic.set_color("#4c8dff")
        else:
            self._mic.set_active(False)
            self._mic.set_color("#3fb950")

    def focus_input(self) -> None:
        self._input.setFocus()

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)
        for index in range(self._messages.count()):
            widget = self._messages.itemAt(index).widget()
            if isinstance(widget, MessageBubble):
                widget.apply_theme(self._theme)
        accent = self._theme.accent
        self._send.set_colors(
            accent,
            self._theme.accent_hover,
            self._theme.accent,
        )
