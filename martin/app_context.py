"""Aplikační kontext - centrální objekt spojující všechny moduly.

Vlastní všechny signály, které UI potřebuje, a drží stav aplikace.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor

from martin.core.logging import get_logger
from martin.core.settings import SettingsStore
from martin.hardware.monitor import HardwareMonitor
from martin.hardware.profiles import HardwareManager
from martin.llm.client import ChatMessage, OllamaClient
from martin.llm.orchestrator import Orchestrator, OrchestratorEvent
from martin.llm.router import ModelRouter
from martin.memory.conversations import ConversationStore
from martin.memory.manager import MemoryManager
from martin.memory.store import MemoryStore
from martin.paths import (
    CONVERSATIONS_DB_PATH,
    DB_PATH,
    SECURITY_LOG_PATH,
    VAD_MODEL_PATH,
    WHISPER_MODELS_DIR,
    WHISPER_VAD_MODEL,
)
from martin.security.audit import AuditLog
from martin.security.engine import PolicyEngine, ToolRegistry
from martin.speech.pipeline import Stage, VoiceEvent, VoicePipeline
from martin.speech.streaming_tts import StreamingTTS
from martin.speech.stt import AudioRecorder, SileroVAD
from martin.speech.whispercpp_backend import WhisperCppBackend
from martin.speech.tts import PiperTTS
from martin.system.apps import AppRegistry
from martin.system.windows import VolumeController
from martin.tools.tools import ToolSet
from martin.vision.analyzer import VisionAnalyzer
from martin.vision.capture import ScreenCapture

log = get_logger("martin.app")

SYSTEM_PROMPT = """\
Jsi Martin, český osobní AI asistent pro Windows 11. Odpovídáš česky.

Chování:
- Odpovědi jsou stručné, konkrétní a v přirozené češtině.
- Pokud něco není jasné, řekni to přímo a zeptej se.
- Nepředstíraj, že jsi něco udělal, pokud jsi to neudělal.
- Nástroje používáš jen když to dává smysl, a vždy přes registrované
  nástroje - nikdy nevydáváš příkazy do shellu.
- Technické termíny ponecháváš v originále (např. VRAM, shader, commit).
"""


class AppContext(QObject):
    """Centrální stav a signály aplikace."""

    stream_started = Signal()
    stream_chunk = Signal(str)
    stream_finished = Signal(str)
    model_changed = Signal(str)
    status_message = Signal(str)
    confirm_requested = Signal(str, dict)
    error_occurred = Signal(str)
    listening_changed = Signal(bool)
    speaking_changed = Signal(bool)
    snapshot_updated = Signal(object)
    profile_changed = Signal(str, str)
    tts_status = Signal(str)
    memory_changed = Signal()
    security_event = Signal(object)
    theme_changed = Signal(object)
    quit_requested = Signal()
    voice_stage = Signal(object)
    voice_diagnostics = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.settings

        # --- audit a bezpečnost ---
        self.audit_log = AuditLog(SECURITY_LOG_PATH)
        self.tool_registry = ToolRegistry()
        self.policy = PolicyEngine(
            self.tool_registry,
            self.audit_log,
            allow_cloud=self.settings.allow_cloud_fallback,
        )

        # --- LLM ---
        self.client = OllamaClient(
            self.settings.ollama_url, timeout=self.settings.request_timeout
        )
        self.router = ModelRouter(self.client)
        self.orchestrator = Orchestrator(
            self.client, self.policy, self.router, SYSTEM_PROMPT
        )

        # --- data ---
        self.memory_store = MemoryStore(DB_PATH)
        self.memory_manager = MemoryManager(self.memory_store)
        self.conversations = ConversationStore(CONVERSATIONS_DB_PATH)

        # --- hardware ---
        self.monitor = HardwareMonitor()
        self.hardware = HardwareManager(
            self.monitor,
            self.settings.ollama_url,
            cloud_allowed=self.settings.allow_cloud_fallback,
        )

        # --- systém ---
        self.app_registry = AppRegistry()
        self.volume = VolumeController()

        # --- hlas ---
        self.tts = PiperTTS(
            self.settings.tts_voice,
            self.settings.tts_rate,
            self.settings.tts_output_device,
        )

        # Mikrofon - kazdy cyklus vytvori vlastni zaznamovac, aby se
        # nestalo, ze predchozi cyklus drzel zarizeni zamcenne.
        self.recorder = AudioRecorder(self.settings.mic_device or None)
        vad = SileroVAD(str(VAD_MODEL_PATH))
        vad.load()
        self.vad = vad

        # Rozpoznani reci - whisper.cpp (faster-whisper je na tomto PC
        # blokovan zasadou WDAC, viz martin/speech/whispercpp_backend.py).
        self.stt_backend = WhisperCppBackend(
            model_size=self.settings.stt_model,
            models_dir=WHISPER_MODELS_DIR,
            language=self.settings.stt_language,
            vad_model_path=WHISPER_VAD_MODEL,
            silence_rms=float(self.settings.extra.get("stt_silence_rms", 0.0008)),
        )
        self.voice_pipeline = VoicePipeline(
            self.stt_backend,
            lambda: AudioRecorder(self.settings.mic_device or None),
            self.tts,
        )
        self.voice_pipeline.set_callbacks(
            on_event=self._on_voice_event,
        )

        # --- vidění ---
        self.screen_capture = ScreenCapture()
        self.vision = VisionAnalyzer(self.client, self.settings.local_model)

        # --- nástroje ---
        self.toolset = ToolSet(
            self.tool_registry,
            self.app_registry,
            self.volume,
            self.memory_manager,
            self._VisionAdapter(self),
            self.hardware,
        )
        self.toolset.register_all()

        self._conversation_id: int | None = None
        self._thread: QThread | None = None
        self._worker: Any | None = None
        self._busy = threading.Event()
        self._listening = False
        self._voice_busy = False
        self._last_model_label = ""

        self.monitor.add_callback(self._on_snapshot)
        self._sync_hardware_profile()
        self._emit_tts_status()

    # -- stav -----------------------------------------------------------
    @property
    def memory_manager(self) -> MemoryManager:
        return self._memory_manager

    @memory_manager.setter
    def memory_manager(self, value: MemoryManager) -> None:
        self._memory_manager = value

    @property
    def conversations(self) -> ConversationStore:
        return self._conversations

    @conversations.setter
    def conversations(self, value: ConversationStore) -> None:
        self._conversations = value

    def current_model_label(self) -> str:
        if not self.client.is_available():
            return "Ollama nedostupná"
        settings = self.settings
        if settings.local_only:
            return settings.local_model
        return f"{settings.local_model} / {settings.cloud_model}"

    def list_models(self) -> list[str]:
        try:
            return self.client.model_names()
        except Exception:  # noqa: BLE001
            return []

    def app_icon(self) -> QIcon:
        """Vytvoří ikonu aplikace (stylizované M)."""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#4c8dff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(34)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "M")
        painter.end()
        return QIcon(pixmap)

    # -- chat -----------------------------------------------------------
    def send_message(self, text: str) -> None:
        """Odešle zprávu modelu (asynchronně, neblokuje UI)."""
        text = (text or "").strip()
        if not text or self._busy.is_set():
            return

        if self._conversation_id is None:
            self._conversation_id = self.conversations.create(
                title=text[:48], model=self.settings.local_model
            )
        self.conversations.add_message(self._conversation_id, "user", text)

        context = self.memory_manager.context_for(text)
        history = self.conversations.get_messages(self._conversation_id)[-8:]
        messages: list[ChatMessage] = []
        if context:
            messages.append(
                ChatMessage(
                    role="system",
                    content=f"Paměť uživatele:\n{context}",
                )
            )
        for item in history:
            if item["role"] == "user":
                messages.append(ChatMessage(role="user", content=item["content"]))
            elif item["role"] == "assistant":
                messages.append(ChatMessage(role="assistant", content=item["content"]))

        self._busy.set()
        self.stream_started.emit()
        self.status_message.emit("Martin přemýšlí...")

        worker = _ChatWorker(self, messages)
        thread = QThread()
        self._worker = worker
        self._thread = thread

        # Worker se presune do vlakna az PO pripojeni signalu - jinak
        # by `started` signal sel az v novem vlakne a `run` se nikdy
        # nezavolal.
        thread.started.connect(worker.run)

        # Signaly z pracovniho vlakna do UI - typovano, aby Qt vedel,
        # ze jde o跨界 signal mezi vlakny.
        worker.chunk.connect(self.stream_chunk)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_worker_error)
        worker.confirm.connect(self._on_worker_confirm)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_finished(self, text: str, info: str) -> None:
        self._busy.clear()
        if self._conversation_id is not None and text.strip():
            self.conversations.add_message(self._conversation_id, "assistant", text)
        self.stream_finished.emit(info)
        self.status_message.emit("Připraven")
        # Hlas přehrává streamovací TTS (viz _ChatWorker) - nechceme
        # odpověď přehrát podruhe.

    def _on_worker_confirm(self, tool: str, args: dict) -> None:
        """Předá žádost o potvrzení do UI a čeká na odpověď.

        UI (MainWindow) zobrazí dialog a zavolá `respond_confirm`.
        Pokud není žádné UI (např. test), akce se po krátké prodlevě
        automaticky zamítne - bezpečná výchozí volba.
        """
        self.confirm_requested.emit(tool, args)

    def _on_worker_error(self, message: str) -> None:
        self._busy.clear()
        self.error_occurred.emit(message)
        self.status_message.emit("Došlo k chybě")

    def load_conversation(self, conversation_id: int) -> None:
        """Načte konverzaci do chatu."""
        self._conversation_id = conversation_id
        messages = self.conversations.get_messages(conversation_id)
        self.status_message.emit(f"Načteno {len(messages)} zpráv")

    # -- potvrzení ------------------------------------------------------
    def respond_confirm(self, approved: bool) -> None:
        self.orchestrator.confirm(approved)

    # -- hlas -----------------------------------------------------------
    def speak(self, text: str) -> None:
        """Přečte text nahlas (v samostatném vlákně)."""
        if not self.settings.tts_enabled or not text.strip():
            return
        if not self.tts.available():
            self.status_message.emit("Hlas není dostupný")
            return
        content = text
        if self.settings.speak_summaries:
            content = self.tts.summarize_for_speech(text)

        def run() -> None:
            try:
                self.speaking_changed.emit(True)
                self.tts.speak(content)
            except Exception as exc:  # noqa: BLE001
                log.warning("Přehrávání hlasu selhalo: %s", exc)
            finally:
                try:
                    self.speaking_changed.emit(False)
                except RuntimeError:
                    # Aplikace se mezitim ukoncuje - signal uz neni platny.
                    pass

        threading.Thread(target=run, name="martin-tts", daemon=True).start()

    def stop_speaking(self) -> None:
        self.tts.stop()
        self.speaking_changed.emit(False)

    def _emit_tts_status(self) -> None:
        info = self.tts.model_info()
        if info.get("available"):
            self.tts_status.emit(
                f"Piper: {info['voice']} ({info.get('size_mb', 0)} MB)"
            )
        else:
            self.tts_status.emit("Piper není dostupný")

    def toggle_listening(self) -> None:
        """Přepne režim poslouchání (push-to-talk).

        Při zapnutí se spustí nahrávání, při vypnutí se zvuk rozpozná
        a odešle modelu jako zpráva. ŽÁDNÝ krok neblokuje GUI vlákno.
        """
        if self._listening:
            self._stop_listening()
        else:
            self._start_listening()

    def _start_listening(self) -> None:
        """Zapne nahrávání - neblokuje GUI vlákno."""
        if self._voice_busy:
            self.status_message.emit("Martin právě mluví - počkej chvíli.")
            return
        # Otevreni mikrofonu bezi v pracovnim vlakne (VoicePipeline).
        self.voice_pipeline.start_recording()
        self._listening = True
        self.listening_changed.emit(True)
        self.status_message.emit("Poslouchám - řekni něco, pak stiskni znovu.")

    def _stop_listening(self) -> None:
        """Zastaví nahrávání a spustí rozpoznání - neblokuje GUI vlákno."""
        self._listening = False
        self.listening_changed.emit(False)
        self.status_message.emit("Rozpoznávám řeč...")

        def run() -> None:
            audio = self.voice_pipeline.stop_recording()
            if audio is None or len(audio) == 0:
                self.status_message.emit("Zaznamenal se žádný zvuk.")
                return
            text = self.voice_pipeline.process_recording(audio)
            if not text:
                # Ticho/šum/halucinace - požadavek se NEODESÍLÁ.
                return
            QTimer.singleShot(0, lambda: self.send_message(text))

        threading.Thread(target=run, name="martin-stt", daemon=True).start()

    def _on_voice_event(self, event: VoiceEvent) -> None:
        """Zpracuje událost z voice pipeline."""
        if event.stage is Stage.RECORDING:
            self.listening_changed.emit(True)
        elif event.stage is Stage.TRANSCRIBING and event.text:
            self.status_message.emit(f"Rozpoznáno: {event.text}")
        elif event.stage is Stage.ERROR:
            self.status_message.emit(event.message or event.error or "Chyba hlasu.")
        if event.diagnostics:
            self.voice_diagnostics.emit(event.diagnostics)
        self.voice_stage.emit(event)

    def cancel_voice(self) -> None:
        """Zruší hlasový cyklus (nahrávání, rozpoznávání i mluvení)."""
        self.voice_pipeline.cancel()
        self._listening = False
        self.listening_changed.emit(False)
        self.stop_speaking()

    def focus_input(self) -> None:
        pass

    # -- nastavení ------------------------------------------------------
    def save_settings(self) -> bool:
        ok = self.settings_store.save()
        if ok:
            self.client = OllamaClient(
                self.settings.ollama_url, timeout=self.settings.request_timeout
            )
            self.orchestrator._client = self.client  # noqa: SLF001
            self.router._client = self.client  # noqa: SLF001
            self.vision._client = self.client  # noqa: SLF001
            self.policy.set_allow_cloud(self.settings.allow_cloud_fallback)
            self.hardware._cloud_allowed = self.settings.allow_cloud_fallback  # noqa: SLF001
            self.tts.set_voice(self.settings.tts_voice)
            self.tts.set_rate(self.settings.tts_rate)
            self.tts.set_output_device(self.settings.tts_output_device)
            self.stt_backend.set_model(self.settings.stt_model)
            self.stt_backend.set_language(self.settings.stt_language)
            self.stt_backend.set_silence_threshold(
                float(self.settings.extra.get("stt_silence_rms", 0.0008))
            )
            self.model_changed.emit(self.current_model_label())
            self._emit_tts_status()
        return ok

    def set_theme(self, name: str) -> None:
        self.settings.theme = name
        self.settings_store.save()
        from martin.ui.theme import get_theme

        theme = get_theme(name)
        self.theme_changed.emit(theme)

    def toggle_theme(self) -> None:
        self.set_theme("light" if self.settings.theme == "dark" else "dark")

    def emit_memory_changed(self) -> None:
        self.memory_changed.emit()

    def clear_audit_log(self) -> None:
        try:
            SECURITY_LOG_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        self.security_event.emit(None)

    # -- hardware -------------------------------------------------------
    def _sync_hardware_profile(self) -> None:
        self.hardware.apply_to_settings(self.settings)
        definition = self.hardware.definition
        self.profile_changed.emit(definition.name, definition.description)

    def _on_snapshot(self, snapshot: Any) -> None:
        self.snapshot_updated.emit(snapshot)

    # -- životní cyklus --------------------------------------------------
    def start(self) -> None:
        """Spustí monitorování a dopredu nacte modely (v pozadi)."""
        self.monitor.start()
        threading.Thread(
            target=self._warm_up_models, name="martin-warmup", daemon=True
        ).start()

    def _warm_up_models(self) -> None:
        """Nacte modely dopredu, aby prvni povel byla rychla.

        Delano V POZADIM vlakne - nikdy v GUI vlakne. Nacitani Piper
        hlasu trva ~6 s a modelu whisper.cpp ~1 s; bez warm-upu by
        prvni odpoved cekala na to.
        """
        if self.settings.tts_enabled:
            self.tts.warm_up()
        try:
            self.stt_backend.warm_up()
        except Exception as exc:  # noqa: BLE001
            log.info("Warm-up STT selhal: %s", exc)

    def shutdown(self) -> None:
        """Ukončí aplikaci - uvolní zdroje."""
        for name, action in (
            ("monitor", self.monitor.stop),
            ("tts", self.tts.stop),
            ("recorder", self.recorder.stop),
            ("client", self.client.close),
        ):
            try:
                action()
            except Exception as exc:  # noqa: BLE001
                log.warning("Ukoncovani %s selhalo: %s", name, exc)

    # -- vnitřní adaptér pro nástroj analyze_screen ---------------------
    class _VisionAdapter:
        """Adaptér, aby nástroj analyze_screen mohl volat vision modul."""

        def __init__(self, ctx: "AppContext") -> None:
            self._ctx = ctx

        def analyze(self, question: str) -> dict[str, Any]:
            from martin.vision.capture import CaptureTarget

            return self._ctx.vision.analyze(question, CaptureTarget())


class _ChatWorker(QObject):
    """Pracovní vlákno, které volá orchestrátor."""

    from PySide6.QtCore import Signal as _Signal

    chunk = _Signal(str)
    finished = _Signal(str, str)
    error = _Signal(str)
    confirm = _Signal(str, dict)

    def __init__(self, ctx: AppContext, messages: list[ChatMessage]) -> None:
        super().__init__()
        self._ctx = ctx
        self._messages = messages

    def run(self) -> None:
        settings = self._ctx.settings
        collected: list[str] = []
        streamer: StreamingTTS | None = None
        first_token: list[float] = []
        llm_start = time.perf_counter()

        # Hlas zacne mluvit uz b behem generovani - neznam es celou
        # odpoved, ale prvni syntetizovana veta se prehraje drive.
        if settings.speak_replies and settings.tts_enabled:
            streamer = StreamingTTS(self._ctx.tts)
            streamer.set_callbacks(on_playback_start=self._on_playback_start)

        def emit(event: OrchestratorEvent, data: dict[str, Any]) -> None:
            if event is OrchestratorEvent.TEXT:
                text = data.get("text", "")
                if text:
                    if not first_token:
                        first_token.append(time.perf_counter() - llm_start)
                        self._ctx.voice_pipeline.timings.llm_first_token_s = (
                            first_token[0]
                        )
                    collected.append(text)
                    self.chunk.emit(text)
                    if streamer is not None:
                        try:
                            streamer.push_text(text)
                        except Exception:  # noqa: BLE001
                            pass
            elif event is OrchestratorEvent.ROUTE:
                self._ctx.model_changed.emit(
                    f"{data.get('model', '')} ({data.get('provider', '')})"
                )
            elif event is OrchestratorEvent.ERROR:
                self.error.emit(str(data.get("message", "Neznámá chyba")))
            elif event is OrchestratorEvent.TOOL_CALL:
                self._ctx.status_message.emit(
                    f"Provádím akci: {data.get('tool', '')}"
                )
            elif event is OrchestratorEvent.CONFIRM_REQUEST:
                # Předání žádosti o potvrzení do UI. Orchestrátor v tuto
                # chvíli čeká na odpověď (max 120 s).
                self._ctx.status_message.emit(
                    f"Vyžaduje potvrzení: {data.get('tool', '')}"
                )
                self.confirm.emit(
                    str(data.get("tool", "")), dict(data.get("args") or {})
                )

        try:
            tools = self._ctx.tool_registry.schemas()
            options = {
                "temperature": settings.temperature,
                "num_ctx": settings.num_ctx,
                "num_predict": settings.max_tokens,
            }
            self._ctx.orchestrator.run(
                self._messages,
                local_model=settings.local_model,
                cloud_model=settings.cloud_model,
                local_only=settings.local_only,
                allow_cloud=settings.allow_cloud_fallback,
                tools=tools,
                options=options,
                emit=emit,
                profile=settings.profile,
                think=settings.thinking,
            )
            llm_total = time.perf_counter() - llm_start
            self._ctx.voice_pipeline.timings.llm_total_s = llm_total
            if streamer is not None:
                try:
                    streamer.finish()
                except Exception:  # noqa: BLE001
                    pass
            self.finished.emit("".join(collected), "")
        except Exception as exc:  # noqa: BLE001
            log.exception("Chat selhal")
            self.error.emit(f"Chat selhal: {exc}")

    def _on_playback_start(self) -> None:
        """Signalizuje, ze zvuk zacal hrat."""
        try:
            self._ctx.speaking_changed.emit(True)
        except RuntimeError:
            pass