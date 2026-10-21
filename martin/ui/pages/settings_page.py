"""Stránka nastavení - všechny parametry Martina."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from martin.ui.animated import AnimatedButton
from martin.ui.theme import get_theme


class SettingsPage(QWidget):
    """Nastavení AI, hlasu, zobrazení a chování."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx
        self._theme = get_theme(ctx.settings.theme)
        self._build()
        self._load()
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
        layout.setSpacing(14)

        layout.addWidget(self._build_ai_group())
        layout.addWidget(self._build_voice_group())
        layout.addWidget(self._build_ui_group())
        layout.addWidget(self._build_behavior_group())
        layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # --- skupiny -------------------------------------------------------
    def _build_ai_group(self) -> QGroupBox:
        box = QGroupBox("Umělá inteligence")
        form = QFormLayout(box)
        form.setSpacing(9)

        self._ollama_url = QLineEdit()
        self._ollama_url.setPlaceholderText("http://127.0.0.1:11434")
        form.addRow("Adresa Ollama:", self._ollama_url)

        self._local_model = QComboBox()
        self._local_model.setEditable(True)
        form.addRow("Lokální model:", self._local_model)

        self._cloud_model = QComboBox()
        self._cloud_model.setEditable(True)
        form.addRow("Cloudový model:", self._cloud_model)

        self._local_only = QCheckBox("Local Only - nikdy nic neposílat do cloudu")
        form.addRow("", self._local_only)

        self._auto_route = QCheckBox("Automaticky volit model podle složitosti")
        form.addRow("", self._auto_route)

        self._thinking = QCheckBox(
            "Režim přemýšlení (přesnější, ale mnohem pomalejší odpovědi)"
        )
        form.addRow("", self._thinking)

        self._allow_cloud = QCheckBox("Povolit cloudový fallback")
        form.addRow("", self._allow_cloud)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        form.addRow("Teplota:", self._temperature)

        self._num_ctx = QSpinBox()
        self._num_ctx.setRange(512, 131072)
        self._num_ctx.setSingleStep(512)
        form.addRow("Kontextové okno:", self._num_ctx)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(128, 32768)
        self._max_tokens.setSingleStep(128)
        form.addRow("Max. tokenů odpovědi:", self._max_tokens)

        buttons = QHBoxLayout()
        self._refresh_models = QPushButton("Načíst modely")
        self._save = AnimatedButton("Uložit")
        buttons.addWidget(self._refresh_models)
        buttons.addStretch(1)
        buttons.addWidget(self._save)
        form.addRow("", buttons)

        return box

    def _build_voice_group(self) -> QGroupBox:
        box = QGroupBox("Hlas a rozpoznávání řeči")
        form = QFormLayout(box)
        form.setSpacing(9)

        self._tts_enabled = QCheckBox("Používat hlasové odpovědi")
        form.addRow("", self._tts_enabled)

        self._tts_voice = QComboBox()
        form.addRow("Hlas Piper:", self._tts_voice)

        self._tts_rate = QDoubleSpinBox()
        self._tts_rate.setRange(0.5, 2.0)
        self._tts_rate.setSingleStep(0.1)
        self._tts_rate.setSuffix(" x")
        form.addRow("Rychlost mluvení:", self._tts_rate)

        self._tts_device = QComboBox()
        form.addRow("Zvukové zařízení:", self._tts_device)

        self._speak_summaries = QCheckBox("Předčítat zkrácené shrnutí dlouhých odpovědí")
        form.addRow("", self._speak_summaries)

        self._stt_model = QComboBox()
        self._stt_model.addItems(["tiny", "base", "small", "medium"])
        form.addRow("Model rozpoznávání:", self._stt_model)

        self._stt_language = QComboBox()
        self._stt_language.addItems(["cs", "en", "auto"])
        form.addRow("Jazyk:", self._stt_language)

        self._mic_device = QComboBox()
        form.addRow("Mikrofon:", self._mic_device)

        self._wake_word = QCheckBox("Používat aktivační slovo")
        form.addRow("", self._wake_word)

        self._wake_text = QLineEdit()
        form.addRow("Aktivační slovo:", self._wake_text)

        return box

    def _build_ui_group(self) -> QGroupBox:
        box = QGroupBox("Vzhled")
        form = QFormLayout(box)
        form.setSpacing(9)

        self._theme_select = QComboBox()
        self._theme_select.addItem("Tmavý", "dark")
        self._theme_select.addItem("Světlý", "light")
        form.addRow("Motiv:", self._theme_select)

        self._font_size = QSpinBox()
        self._font_size.setRange(8, 16)
        form.addRow("Velikost písma:", self._font_size)

        self._animations = QCheckBox("Povolit animace")
        form.addRow("", self._animations)

        self._floating = QCheckBox("Používat plovoucí okno")
        form.addRow("", self._floating)

        self._start_minimized = QCheckBox("Spustit minimalizovaný v tray")
        form.addRow("", self._start_minimized)

        return box

    def _build_behavior_group(self) -> QGroupBox:
        box = QGroupBox("Chování a bezpečnost")
        form = QFormLayout(box)
        form.setSpacing(9)

        self._profile = QComboBox()
        self._profile.addItem("PERFORMANCE - maximální výkon", "PERFORMANCE")
        self._profile.addItem("GAMING - uvolní VRAM pro hry", "GAMING")
        self._profile.addItem("SMART - automatické volení", "SMART")
        form.addRow("Profil výkonu:", self._profile)

        self._speak_replies = QCheckBox("Předčítat odpovědi")
        form.addRow("", self._speak_replies)

        self._log_security = QCheckBox("Zaznamenávat bezpečnostní rozhodnutí")
        form.addRow("", self._log_security)

        self._status = QLabel("")
        self._status.setObjectName("Subtitle")
        form.addRow("", self._status)

        return box

    # --- načtení / uložení ----------------------------------------------
    def _load(self) -> None:
        settings = self._ctx.settings
        self._ollama_url.setText(settings.ollama_url)
        self._local_model.setCurrentText(settings.local_model)
        self._cloud_model.setCurrentText(settings.cloud_model)
        self._local_only.setChecked(settings.local_only)
        self._auto_route.setChecked(settings.auto_route)
        self._thinking.setChecked(settings.thinking)
        self._allow_cloud.setChecked(settings.allow_cloud_fallback)
        self._temperature.setValue(settings.temperature)
        self._num_ctx.setValue(settings.num_ctx)
        self._max_tokens.setValue(settings.max_tokens)

        self._tts_enabled.setChecked(settings.tts_enabled)
        self._tts_voice.setCurrentText(settings.tts_voice)
        self._tts_rate.setValue(settings.tts_rate)
        self._speak_summaries.setChecked(settings.speak_summaries)
        self._stt_model.setCurrentText(settings.stt_model)
        self._stt_language.setCurrentText(settings.stt_language)
        self._wake_word.setChecked(settings.wake_word_enabled)
        self._wake_text.setText(settings.wake_word)

        self._theme_select.setCurrentIndex(
            0 if settings.theme == "dark" else 1
        )
        self._font_size.setValue(settings.font_size)
        self._animations.setChecked(settings.animations_enabled)
        self._floating.setChecked(settings.floating_window)
        self._start_minimized.setChecked(settings.start_minimized)

        self._profile.setCurrentIndex(
            {"PERFORMANCE": 0, "GAMING": 1, "SMART": 2}.get(settings.profile, 2)
        )
        self._speak_replies.setChecked(settings.speak_replies)
        self._log_security.setChecked(settings.log_security)
        self._refresh_model_list()

    def _refresh_model_list(self) -> None:
        try:
            models = self._ctx.list_models()
        except Exception as exc:  # noqa: BLE001
            models = []
            self._status.setText(f"Nelze načíst modely: {exc}")
        if not models:
            return
        for combo in (self._local_model, self._cloud_model):
            current = combo.currentText()
            combo.clear()
            combo.addItems(models)
            combo.setCurrentText(current)

    def _connect(self) -> None:
        self._save.clicked.connect(self._save_settings)
        self._refresh_models.clicked.connect(self._refresh_model_list)
        self._theme_select.currentIndexChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self) -> None:
        theme = self._theme_select.currentData()
        self._ctx.set_theme(theme)

    def _save_settings(self) -> None:
        settings = self._ctx.settings
        settings.ollama_url = self._ollama_url.text().strip()
        settings.local_model = self._local_model.currentText().strip()
        settings.cloud_model = self._cloud_model.currentText().strip()
        settings.local_only = self._local_only.isChecked()
        settings.auto_route = self._auto_route.isChecked()
        settings.thinking = self._thinking.isChecked()
        settings.allow_cloud_fallback = self._allow_cloud.isChecked()
        settings.temperature = self._temperature.value()
        settings.num_ctx = self._num_ctx.value()
        settings.max_tokens = self._max_tokens.value()

        settings.tts_enabled = self._tts_enabled.isChecked()
        settings.tts_voice = self._tts_voice.currentText().strip()
        settings.tts_rate = self._tts_rate.value()
        settings.speak_summaries = self._speak_summaries.isChecked()
        settings.stt_model = self._stt_model.currentText().strip()
        settings.stt_language = self._stt_language.currentText().strip()
        settings.mic_device = self._mic_device.currentData() or ""
        settings.wake_word_enabled = self._wake_word.isChecked()
        settings.wake_word = self._wake_text.text().strip() or "martine"

        settings.font_size = self._font_size.value()
        settings.animations_enabled = self._animations.isChecked()
        settings.floating_window = self._floating.isChecked()
        settings.start_minimized = self._start_minimized.isChecked()

        settings.profile = self._profile.currentData() or "SMART"
        settings.speak_replies = self._speak_replies.isChecked()
        settings.log_security = self._log_security.isChecked()

        if self._ctx.save_settings():
            self._status.setText("Nastavení uloženo.")
        else:
            self._status.setText("Nastavení se nepodařilo uložit.")

    def refresh_theme(self) -> None:
        self._theme = get_theme(self._ctx.settings.theme)
        accent = self._theme.accent
        self._save.set_colors(accent, self._theme.accent_hover, accent)