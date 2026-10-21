"""Dolní stavový řádek - model, mikrofon, TTS, systémové zdroje."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
)

from martin.ui.animated import PulseIndicator
from martin.ui.theme import get_theme


class StatusBar(QFrame):
    """Stavový řádek aplikace."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx
        self._theme = get_theme(ctx.settings.theme)
        self.setObjectName("StatusBar")
        self.setFixedHeight(34)
        self._build()
        self._connect()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(14)

        self._model = QLabel("Model: —")
        layout.addWidget(self._model)

        self._provider = QLabel("")
        self._provider.setObjectName("Subtitle")
        layout.addWidget(self._provider)

        layout.addStretch(1)

        self._mic_indicator = PulseIndicator("#3fb950", self)
        self._mic_indicator.setToolTip("Mikrofon")
        layout.addWidget(self._mic_indicator)
        self._mic_label = QLabel("Mikrofon")
        self._mic_label.setObjectName("Subtitle")
        layout.addWidget(self._mic_label)

        self._tts_label = QLabel("Hlas: vypnut")
        self._tts_label.setObjectName("Subtitle")
        layout.addWidget(self._tts_label)

        self._message = QLabel("")
        self._message.setObjectName("Subtitle")
        self._message.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._message)

        self._cpu = self._make_meter("CPU", layout)
        self._gpu = self._make_meter("GPU", layout)
        self._ram = self._make_meter("RAM", layout)

    def _make_meter(self, label: str, layout: QHBoxLayout) -> QProgressBar:
        text = QLabel(label)
        text.setObjectName("Subtitle")
        layout.addWidget(text)
        bar = QProgressBar()
        bar.setMaximumWidth(74)
        bar.setTextVisible(False)
        bar.setRange(0, 100)
        layout.addWidget(bar)
        return bar

    def _connect(self) -> None:
        self._ctx.model_changed.connect(self._on_model)
        self._ctx.listening_changed.connect(self._on_listening)
        self._ctx.speaking_changed.connect(self._on_speaking)
        self._ctx.snapshot_updated.connect(self._on_snapshot)

    def _on_model(self, label: str) -> None:
        self._model.setText(f"Model: {label}")

    def _on_listening(self, active: bool) -> None:
        self._mic_indicator.set_active(active)
        self._mic_indicator.set_color("#f85149" if active else "#3fb950")
        self._mic_label.setText("Poslouchám" if active else "Mikrofon")

    def _on_speaking(self, active: bool) -> None:
        self._tts_label.setText("Mluví" if active else "Hlas: připraven")

    def _on_snapshot(self, snapshot: Any) -> None:
        self._cpu.setValue(int(snapshot.cpu_percent))
        self._gpu.setValue(int(snapshot.gpu_utilization))
        self._ram.setValue(int(snapshot.ram_percent))

    def show_message(self, text: str) -> None:
        self._message.setText(text)

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {self._theme.bg_alt};
                border-top: 1px solid {self._theme.border};
            }}
            QLabel {{ background: transparent; border: none; }}
            QProgressBar {{
                background: {self._theme.surface_alt};
                border: none;
                border-radius: 3px;
                height: 6px;
            }}
            QProgressBar::chunk {{
                background: {self._theme.accent};
                border-radius: 3px;
            }}
            """
        )