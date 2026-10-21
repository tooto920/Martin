"""Stránka nastavení - všechny parametry Martina."""

from __future__ import annotations

from typing import Any
import json

from PySide6.QtCore import QTimer

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
    QPlainTextEdit,
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
        self._usage_timer = QTimer(self)
        self._usage_timer.setInterval(10000)
        self._usage_timer.timeout.connect(self._update_usage)
        self._usage_timer.start()
        self._ctx.operation_result.connect(self._diagnostic_result)
        self._ctx.request_diagnostics.connect(lambda _: self._update_usage(force=True))
        self._update_usage(force=True)

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
        layout.addWidget(self._build_cloud_group())
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

        self._ai_mode = QComboBox()
        self._ai_mode.addItems(["Cloud", "Automatic", "Offline"])
        self._ai_mode.setToolTip(
            "Cloud a Automatic používají cloud. Lokální model se načte jen v režimu Offline. Chyba nikdy sama nespustí placený retry ani lokální fallback."
        )
        form.addRow("Režim AI:", self._ai_mode)

        self._ollama_url = QLineEdit()
        self._ollama_url.setPlaceholderText("http://127.0.0.1:11434")
        form.addRow("Adresa Ollama:", self._ollama_url)

        self._local_model = QComboBox()
        self._local_model.setEditable(True)
        form.addRow("Lokální model:", self._local_model)

        self._cloud_model = QComboBox()
        self._cloud_model.setEditable(True)
        form.addRow("Cloudový model:", self._cloud_model)

        self._vision_model = QLineEdit()
        form.addRow("Cloudový model obrazu:", self._vision_model)

        self._local_only = QCheckBox("Local Only - nikdy nic neposílat do cloudu")
        self._local_only.hide()

        self._auto_route = QCheckBox("Automaticky volit model podle složitosti")
        self._auto_route.hide()

        self._thinking = QCheckBox("Režim přemýšlení (přesnější, ale mnohem pomalejší odpovědi)")
        form.addRow("", self._thinking)

        self._allow_cloud = QCheckBox("Povolit cloudový fallback")
        self._allow_cloud.hide()

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

    def _build_cloud_group(self):
        box = QGroupBox("Model Management / Cloud Usage")
        form = QFormLayout(box)
        notice = QLabel(
            "Cloud odesílá text a posledních 8 zpráv (každá nejvýše 6000 znaků). Relevantní paměť a snímky jsou samostatně volitelné. Dokumenty ani přihlašovací soubory se automaticky neodesílají. Offline zakáže cloudové inference."
        )
        notice.setWordWrap(True)
        form.addRow(notice)
        self._cloud_memory = QCheckBox("Povolit relevantní paměť v cloudu (max. 4000 znaků)")
        self._cloud_images = QCheckBox(
            "Povolit cloudové snímky — vždy s dalším jednorázovým potvrzením"
        )
        form.addRow(self._cloud_memory)
        form.addRow(self._cloud_images)
        self._window = QLineEdit()
        self._window.setPlaceholderText("Přesný název konkrétního okna; prázdné = žádný snímek")
        form.addRow("Okno pro snímek:", self._window)
        self._gaming_auto = QCheckBox("Automatický herní režim při běhu MSFS")
        form.addRow(self._gaming_auto)
        self._request_timeout = QSpinBox()
        self._request_timeout.setRange(5, 180)
        self._request_timeout.setSuffix(" s")
        form.addRow("Celkový limit požadavku:", self._request_timeout)
        self._daily_budget = QDoubleSpinBox()
        self._monthly_budget = QDoubleSpinBox()
        for spin in (self._daily_budget, self._monthly_budget):
            spin.setRange(0, 10000)
            spin.setDecimals(4)
            spin.setSuffix(" USD; 0 = vypnuto")
        form.addRow("Místní denní rozpočet:", self._daily_budget)
        form.addRow("Místní měsíční rozpočet:", self._monthly_budget)
        self._daily_requests = QSpinBox()
        self._daily_tokens = QSpinBox()
        self._daily_requests.setRange(0, 1000000)
        self._daily_tokens.setRange(0, 1000000000)
        form.addRow("Denní požadavky (0 bez limitu):", self._daily_requests)
        form.addRow("Denní tokeny (0 bez limitu):", self._daily_tokens)
        self._rates = QPlainTextEdit()
        self._rates.setMaximumHeight(105)
        self._rates.setToolTip(
            "JSON: přesný model: [vstup, výstup, cached vstup] v USD za milion tokenů. Pouze odhad. Neznámé ceny nevyplňuj nulou."
        )
        form.addRow("Sazby / 1M tokenů (JSON):", self._rates)
        self._rates_date = QLineEdit()
        form.addRow("Datum sazeb:", self._rates_date)
        link = QLabel(
            '<a href="https://ollama.com/settings/usage">Oficiální spotřeba / kredit účtu</a> · <a href="https://ollama.com/pricing">Ceník</a>'
        )
        link.setOpenExternalLinks(True)
        form.addRow(link)
        self._usage_text = QLabel()
        self._usage_text.setWordWrap(True)
        form.addRow(self._usage_text)
        self._model_state = QLabel(
            "Dostupnost a přihlášení zatím neověřeny. Test spojení provede jednu skutečnou inferenci."
        )
        self._model_state.setWordWrap(True)
        form.addRow(self._model_state)
        self._diag_buttons = {}
        for key, title in (
            ("connection", "Test cloud spojení"),
            ("model", "Test vybraného modelu"),
            ("microphone", "Test mikrofonu"),
            ("voice", "Test hlasu"),
            ("unload", "Uvolnit Martinovy nepoužívané modely"),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, k=key: self._ctx.run_diagnostic(k))
            self._diag_buttons[key] = button
            form.addRow(button)
        stop = QPushButton("Stop generování / hlasu")
        stop.clicked.connect(self._ctx.stop_generation)
        form.addRow(stop)
        retry = QPushButton("Zkusit poslední zprávu znovu")
        retry.clicked.connect(self._ctx.retry_message)
        form.addRow(retry)
        return box

    def _diagnostic_result(self, name, data):
        if name == "models" and data.get("ok"):
            for combo in (self._local_model, self._cloud_model):
                current = combo.currentText()
                combo.clear()
                combo.addItems(data["models"])
                combo.setCurrentText(current)
        else:
            self._model_state.setText(json.dumps(data, ensure_ascii=False, indent=2))

    def _update_usage(self, force=False):
        if not force and not self.isVisible():
            return
        data = self._ctx.usage.snapshot()
        parts = [
            "Zůstatek kreditu: není dostupný přes použitou inferenční API. Skutečné účtování ověř na webu."
        ]
        for key, label in (("day", "Dnes UTC"), ("month", "Měsíc UTC")):
            d = data[key]
            cost = d["estimated_usd"]
            parts.append(
                f"{label}: {d['requests']} požadavků; vstup {d['input_tokens'] if d['input_tokens'] is not None else 'nezjištěn'}, výstup {d['output_tokens'] if d['output_tokens'] is not None else 'nezjištěn'} tokenů; odhad "
                + (f"{cost:.6f} USD" if cost is not None else "nezjištěn")
                + f"; neznámá cena u {d['unknown_cost_requests']} požadavků."
            )
        last = data["last"]
        if last:
            parts.append(
                f"Poslední: {last.get('model')}, ID {last.get('request_id')}, {last.get('status')}, TTFT {last.get('ttft_s', 'nezjištěno')} s; celkem {last.get('elapsed_s', 'nezjištěno')} s."
            )
        parts.append(
            f"Sazby: {data['rates_date']}. Odhad není faktura; místní limity neomezují jiné aplikace. Přerušený požadavek může být účtován."
        )
        for key, label, limit in (
            ("day", "Denní", self._ctx.settings.daily_budget_usd),
            ("month", "Měsíční", self._ctx.settings.monthly_budget_usd),
        ):
            cost = data[key]["estimated_usd"] or 0
            if limit and cost >= 0.8 * limit:
                parts.append(
                    f"Upozornění: {label} odhadovaný rozpočet je čerpán z {cost / limit:.0%}."
                )
        self._usage_text.setText("\n".join(parts))

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
        self._stt_model.setToolTip(
            "whisper.cpp modely. 'small' je doporuceno pro cesku; proti kratke je 'base' rychlejsi."
        )
        form.addRow("Model rozpoznávání:", self._stt_model)

        self._stt_info = QLabel("")
        self._stt_info.setObjectName("Subtitle")
        self._stt_info.setWordWrap(True)
        form.addRow("", self._stt_info)

        self._stt_silence = QDoubleSpinBox()
        self._stt_silence.setRange(0.0, 0.01)
        self._stt_silence.setSingleStep(0.0002)
        self._stt_silence.setDecimals(3)
        form.addRow("Práh ticha (RMS):", self._stt_silence)

        self._stt_language = QComboBox()
        self._stt_language.addItems(["cs", "en", "auto"])
        form.addRow("Jazyk:", self._stt_language)

        self._mic_device = QComboBox()
        self._mic_device.setEditable(True)
        form.addRow("Mikrofon:", self._mic_device)

        self._refresh_voices()
        self._refresh_audio_devices()

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
        self._ai_mode.setCurrentText(settings.ai_mode)
        self._vision_model.setText(settings.vision_model)
        self._cloud_memory.setChecked(settings.cloud_memory_enabled)
        self._cloud_images.setChecked(settings.cloud_images_enabled)
        self._window.setText(settings.screenshot_window)
        self._gaming_auto.setChecked(settings.gaming_auto)
        self._request_timeout.setValue(int(settings.request_timeout))
        self._daily_budget.setValue(settings.daily_budget_usd)
        self._monthly_budget.setValue(settings.monthly_budget_usd)
        self._daily_requests.setValue(settings.daily_request_limit)
        self._daily_tokens.setValue(settings.daily_token_limit)
        self._rates.setPlainText(json.dumps(settings.model_rates, ensure_ascii=False, indent=2))
        self._rates_date.setText(settings.rates_date)
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
        if settings.mic_device:
            index = self._mic_device.findData(str(settings.mic_device))
            if index >= 0:
                self._mic_device.setCurrentIndex(index)
            else:
                self._mic_device.setCurrentText(settings.mic_device)
        if settings.tts_output_device:
            index = self._tts_device.findData(str(settings.tts_output_device))
            if index >= 0:
                self._tts_device.setCurrentIndex(index)
        self._tts_rate.setValue(settings.tts_rate)
        self._speak_summaries.setChecked(settings.speak_summaries)
        self._stt_model.setCurrentText(settings.stt_model)
        self._stt_language.setCurrentText(settings.stt_language)
        self._stt_silence.setValue(float(settings.extra.get("stt_silence_rms", 0.0008)))
        self._refresh_stt_info()
        self._wake_word.setChecked(settings.wake_word_enabled)
        self._wake_text.setText(settings.wake_word)

        self._theme_select.setCurrentIndex(0 if settings.theme == "dark" else 1)
        self._font_size.setValue(settings.font_size)
        self._animations.setChecked(settings.animations_enabled)
        self._floating.setChecked(settings.floating_window)
        self._start_minimized.setChecked(settings.start_minimized)

        self._profile.setCurrentIndex(
            {"PERFORMANCE": 0, "GAMING": 1, "SMART": 2}.get(settings.profile, 2)
        )
        self._speak_replies.setChecked(settings.speak_replies)
        self._log_security.setChecked(settings.log_security)

    def _refresh_voices(self) -> None:
        """Naplní seznam dostupných českých hlasů Piper."""
        try:
            from martin.speech.tts import PiperTTS

            voices = PiperTTS().available_voices()
        except Exception:  # noqa: BLE001
            voices = []
        current = self._tts_voice.currentText()
        self._tts_voice.clear()
        self._tts_voice.addItems(voices)
        if current:
            self._tts_voice.setCurrentText(current)
        elif voices:
            self._tts_voice.setCurrentText(voices[0])

    def _refresh_audio_devices(self) -> None:
        """Naplní seznamy mikrofonů a výstupních zařízení."""
        try:
            import sounddevice as sd  # type: ignore

            devices = sd.query_devices()
        except Exception:  # noqa: BLE001
            return

        current_mic = self._mic_device.currentText()
        current_out = self._tts_device.currentText()

        self._mic_device.clear()
        self._mic_device.addItem("", "")
        self._tts_device.clear()
        self._tts_device.addItem("", "")

        for device in devices:
            name = str(device["name"])
            if device["max_input_channels"] > 0:
                self._mic_device.addItem(f"{name} ({device['index']})", str(device["index"]))
            if device["max_output_channels"] > 0:
                self._tts_device.addItem(f"{name} ({device['index']})", str(device["index"]))

        if current_mic:
            self._mic_device.setCurrentText(current_mic)
        if current_out:
            self._tts_device.setCurrentText(current_out)

    def _refresh_stt_info(self) -> None:
        """Zobrazí stav rozpoznávání řeči (backend, model, VAD)."""
        try:
            from martin.speech.whispercpp_backend import WhisperCppBackend
            from martin.paths import WHISPER_MODELS_DIR, WHISPER_VAD_MODEL

            backend = WhisperCppBackend(
                model_size=self._stt_model.currentText() or "small",
                models_dir=WHISPER_MODELS_DIR,
                vad_model_path=WHISPER_VAD_MODEL,
            )
            status = backend.status()
            if not status["available"]:
                self._stt_info.setText("Backend whisper.cpp není dostupný v tomto systému.")
            elif not status["model_present"]:
                self._stt_info.setText(
                    f"Model '{status['model_size']}' není stažen (hledáno v {WHISPER_MODELS_DIR})."
                )
            else:
                vad = "VAD ano" if status["vad_present"] else "VAD ne"
                self._stt_info.setText(
                    f"whisper.cpp - model {status['model_size']} ({vad}). "
                    "Ticho se automaticky odfiltruje."
                )
        except Exception as exc:  # noqa: BLE001
            self._stt_info.setText(f"Stav rozpoznávání: {exc}")

    def _refresh_model_list(self) -> None:
        self._ctx.run_diagnostic("models")
        return

    def _connect(self) -> None:
        self._save.clicked.connect(self._save_settings)
        self._refresh_models.clicked.connect(self._refresh_model_list)
        self._theme_select.currentIndexChanged.connect(self._on_theme_changed)
        self._stt_model.currentIndexChanged.connect(self._refresh_stt_info)

    def _on_theme_changed(self) -> None:
        theme = self._theme_select.currentData()
        self._ctx.set_theme(theme)

    def _save_settings(self) -> None:
        if (
            self._ctx._busy.is_set()
            or self._ctx._listening
            or any(t.is_alive() for t in self._ctx._diagnostic_threads)
        ):
            self._status.setText("Nejdřív dokonči aktuální operaci.")
            return
        try:
            import math

            rates = json.loads(self._rates.toPlainText())
            if not isinstance(rates, dict) or any(
                not isinstance(v, list)
                or len(v) != 3
                or any(
                    isinstance(n, bool)
                    or not isinstance(n, (int, float))
                    or not math.isfinite(n)
                    or n < 0
                    for n in v
                )
                for v in rates.values()
            ):
                raise ValueError(
                    "Očekáván objekt model: [vstup, výstup, cache] s nezápornými konečnými sazbami."
                )
        except (ValueError, TypeError) as exc:
            self._status.setText(f"Neplatný ceník: {exc}")
            return
        settings = self._ctx.settings
        settings.ai_mode = self._ai_mode.currentText()
        settings.vision_model = self._vision_model.text().strip()
        settings.cloud_memory_enabled = self._cloud_memory.isChecked()
        settings.cloud_images_enabled = self._cloud_images.isChecked()
        settings.screenshot_window = self._window.text().strip()
        settings.gaming_auto = self._gaming_auto.isChecked()
        settings.request_timeout = self._request_timeout.value()
        settings.daily_budget_usd = self._daily_budget.value()
        settings.monthly_budget_usd = self._monthly_budget.value()
        settings.daily_request_limit = self._daily_requests.value()
        settings.daily_token_limit = self._daily_tokens.value()
        settings.model_rates = rates
        settings.rates_date = self._rates_date.text().strip()
        settings.ollama_url = self._ollama_url.text().strip()
        settings.local_model = self._local_model.currentText().strip()
        settings.cloud_model = self._cloud_model.currentText().strip()
        settings.local_only = settings.ai_mode == "Offline"
        settings.auto_route = settings.ai_mode != "Offline"
        settings.thinking = self._thinking.isChecked()
        settings.allow_cloud_fallback = settings.ai_mode != "Offline"
        settings.temperature = self._temperature.value()
        settings.num_ctx = self._num_ctx.value()
        settings.max_tokens = self._max_tokens.value()

        settings.tts_enabled = self._tts_enabled.isChecked()
        settings.tts_voice = self._tts_voice.currentText().strip()
        settings.tts_rate = self._tts_rate.value()
        settings.speak_summaries = self._speak_summaries.isChecked()
        settings.stt_model = self._stt_model.currentText().strip()
        settings.stt_language = self._stt_language.currentText().strip()
        settings.extra["stt_silence_rms"] = self._stt_silence.value()
        mic_data = self._mic_device.currentData()
        index = self._mic_device.currentIndex()
        if index < 0 or self._mic_device.currentText() != self._mic_device.itemText(index):
            settings.mic_device = self._mic_device.currentText().strip()
        elif mic_data is not None:
            settings.mic_device = str(mic_data)
        settings.tts_output_device = str(self._tts_device.currentData() or "")
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
