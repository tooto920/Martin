"""Plovoucí okno Martina - rychlé dotazy z plochy."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from martin.ui.theme import get_theme


class FloatingWindow(QWidget):
    """Malé plovoucí okno s polem pro rychlý dotaz."""

    quick_ask = Signal(str)

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx
        self._theme = get_theme(ctx.settings.theme)
        self.setWindowTitle("Martin")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(380, 78)
        self._build()
        self._apply_style()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        frame = QFrame()
        frame.setObjectName("FloatingFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        icon = QLabel("M")
        icon.setFixedSize(26, 26)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Zeptej se Martina...")
        self._input.returnPressed.connect(self._submit)
        layout.addWidget(self._input, 1)

        outer.addWidget(frame)

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.quick_ask.emit(text)

    def focus_input(self) -> None:
        self.show()
        self.raise_()
        self._input.setFocus()

    def _apply_style(self) -> None:
        theme = self._theme
        self.setStyleSheet(
            f"""
            QFrame#FloatingFrame {{
                background-color: {theme.surface};
                border: 1px solid {theme.accent};
                border-radius: 14px;
            }}
            QLineEdit {{
                background: transparent;
                border: none;
                color: {theme.text};
                font-size: 10pt;
            }}
            QLabel {{
                background-color: {theme.accent};
                color: {theme.accent_text};
                border-radius: 13px;
                font-weight: 700;
            }}
            """
        )

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)
        self._apply_style()