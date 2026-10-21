"""Panel monitorování hardwaru - CPU, RAM, VRAM, teplota, baterie."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from martin.ui.theme import get_theme


class StatTile(QFrame):
    """Jedna dlaždice se statistikou."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatTile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._value = QLabel("—")
        self._value.setObjectName("StatValue")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value)

        self._label = QLabel(label)
        self._label.setObjectName("StatLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(5)
        layout.addWidget(self._bar)

    def set_value(self, value: float, text: str | None = None) -> None:
        self._value.setText(text if text is not None else f"{value:.0f} %")
        self._bar.setValue(int(max(0, min(100, value))))

    def set_sublabel(self, text: str) -> None:
        self._label.setText(text)


class MonitorPanel(QWidget):
    """Pravý panel - stav systému a profil."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx
        self._theme = get_theme(ctx.settings.theme)
        self.setMinimumWidth(300)
        self._build()
        self._connect()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --- Hardware ---
        hardware = QGroupBox("Hardware")
        hw_layout = QVBoxLayout(hardware)
        hw_layout.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(8)
        self._cpu = StatTile("CPU")
        self._gpu = StatTile("GPU")
        self._ram = StatTile("RAM")
        self._vram = StatTile("VRAM")
        grid.addWidget(self._cpu, 0, 0)
        grid.addWidget(self._gpu, 0, 1)
        grid.addWidget(self._ram, 1, 0)
        grid.addWidget(self._vram, 1, 1)
        hw_layout.addLayout(grid)

        self._gpu_name = QLabel("—")
        self._gpu_name.setObjectName("Subtitle")
        self._gpu_name.setWordWrap(True)
        hw_layout.addWidget(self._gpu_name)

        self._detail = QLabel("—")
        self._detail.setObjectName("Subtitle")
        self._detail.setWordWrap(True)
        hw_layout.addWidget(self._detail)
        layout.addWidget(hardware)

        # --- Profil ---
        profile_box = QGroupBox("Profil výkonu")
        profile_layout = QVBoxLayout(profile_box)
        profile_layout.setSpacing(6)
        self._profile = QLabel("SMART")
        self._profile.setObjectName("StatValue")
        profile_layout.addWidget(self._profile)
        self._profile_detail = QLabel("—")
        self._profile_detail.setObjectName("Subtitle")
        self._profile_detail.setWordWrap(True)
        profile_layout.addWidget(self._profile_detail)
        layout.addWidget(profile_box)

        # --- Hlas ---
        voice_box = QGroupBox("Hlas")
        voice_layout = QVBoxLayout(voice_box)
        voice_layout.setSpacing(4)
        self._voice = QLabel("—")
        self._voice.setObjectName("Subtitle")
        self._voice.setWordWrap(True)
        voice_layout.addWidget(self._voice)
        self._mic_state = QLabel("Mikrofon: neaktivní")
        self._mic_state.setObjectName("Subtitle")
        voice_layout.addWidget(self._mic_state)
        layout.addWidget(voice_box)

        # --- Diagnostika hlasu ---
        voice_diag = QGroupBox("Hlasová diagnostika")
        diag_layout = QVBoxLayout(voice_diag)
        diag_layout.setSpacing(4)
        self._timings = QLabel("Zatím bez měření")
        self._timings.setObjectName("Subtitle")
        self._timings.setWordWrap(True)
        diag_layout.addWidget(self._timings)
        self._stt_info = QLabel("STT: nezjištěno")
        self._stt_info.setObjectName("Subtitle")
        self._stt_info.setWordWrap(True)
        diag_layout.addWidget(self._stt_info)
        layout.addWidget(voice_diag)

        layout.addStretch(1)

    def _connect(self) -> None:
        self._ctx.snapshot_updated.connect(self._on_snapshot)
        self._ctx.profile_changed.connect(self._on_profile)
        self._ctx.listening_changed.connect(self._on_listening)
        self._ctx.speaking_changed.connect(self._on_speaking)
        self._ctx.tts_status.connect(self._on_tts)
        self._ctx.voice_diagnostics.connect(self._on_voice_diagnostics)
        self._ctx.voice_stage.connect(self._on_voice_stage)

    def _on_snapshot(self, snapshot: Any) -> None:
        self._cpu.set_value(snapshot.cpu_percent)
        self._gpu.set_value(snapshot.gpu_utilization)
        self._ram.set_value(snapshot.ram_percent)
        self._vram.set_value(
            snapshot.vram_percent, f"{snapshot.gpu_memory_used_mb:.0f} MB"
        )
        self._gpu_name.setText(snapshot.gpu_name or "GPU nedostupné")
        temp = (
            f"{snapshot.temperature_c:.0f} °C"
            if snapshot.temperature_c is not None
            else "—"
        )
        battery = (
            f"{snapshot.battery_percent:.0f} %"
            if snapshot.battery_percent is not None
            else "—"
        )
        self._detail.setText(
            f"Teplota: {temp}   Baterie: {battery}\n"
            f"VRAM: {snapshot.vram_free_mb:.0f} MB volných z "
            f"{snapshot.gpu_memory_total_mb:.0f} MB"
        )

    def _on_profile(self, name: str, detail: str) -> None:
        self._profile.setText(name)
        self._profile_detail.setText(detail)

    def _on_listening(self, active: bool) -> None:
        self._mic_state.setText(
            "Mikrofon: poslouchám" if active else "Mikrofon: neaktivní"
        )

    def _on_speaking(self, active: bool) -> None:
        if active:
            self._mic_state.setText("Mikrofon: mluvím")

    def _on_tts(self, info: str) -> None:
        self._voice.setText(info)

    def _on_voice_diagnostics(self, data: dict) -> None:
        """Zobrazí diagnostiku posledního hlasového cyklu."""
        if not isinstance(data, dict):
            return
        timings = data.get("timings") or {}
        backend = data.get("backend", "")
        if timings:
            parts = []
            for key, label in (
                ("mic_activation_s", "mikrofon"),
                ("record_duration_s", "nahrávání"),
                ("stt_s", "STT"),
                ("llm_first_token_s", "LLM 1. token"),
                ("llm_total_s", "LLM celkem"),
                ("tts_synth_s", "TTS"),
                ("playback_start_s", "přehrávání"),
                ("end_to_end_s", "celkem"),
            ):
                value = timings.get(key)
                if value is not None:
                    parts.append(f"{label} {value:.2f} s")
            self._timings.setText("\n".join(parts))
        reason = data.get("rejected_reason")
        if reason:
            self._stt_info.setText(f"STT ({backend}): odmítnuto - {reason}")
        elif backend:
            self._stt_info.setText(
                f"STT ({backend}): {data.get('segment_count', 0)} segmentů, "
                f"rms {data.get('audio_rms', 0):.4f}"
            )

    def _on_voice_stage(self, event: Any) -> None:
        """Zobrazí aktuální fázi hlasového cyklu."""
        stage = getattr(event, "stage", None)
        if stage is None:
            return
        name = getattr(stage, "value", str(stage))
        if name in ("recording", "transcribing"):
            self._stt_info.setText(f"STT: {name}")

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)
        self.setStyleSheet(
            f"""
            QGroupBox {{
                background-color: {self._theme.surface};
                border: 1px solid {self._theme.border};
                border-radius: 10px;
                margin-top: 10px;
                padding: 10px 8px 8px 8px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
                color: {self._theme.text_dim};
            }}
            QFrame#StatTile {{
                background-color: {self._theme.surface_alt};
                border: 1px solid {self._theme.border};
                border-radius: 8px;
            }}
            QLabel {{ background: transparent; border: none; }}
            QProgressBar {{
                background: {self._theme.bg_alt};
                border: none;
                border-radius: 3px;
                height: 5px;
            }}
            QProgressBar::chunk {{
                background: {self._theme.accent};
                border-radius: 3px;
            }}
            """
        )