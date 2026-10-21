"""Voice pipeline - asynchronní zpracování hlasového příkazu.

Cíle:
  * GUI vlákno nikdy neblokuje (žádné nahrávání, žádné rozpoznávání,
    žádná syntéza, žádné čekání na LLM).
  * Každý krok má změřitelnou dobu.
  * Přerušení je možné v každém kroku.
  * Tichá nahrávka nikdy nevytvoří požadavek pro LLM.

Tok: nahrávání -> STT -> (kontrola) -> LLM -> TTS -> přehrávání
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import numpy as np

from martin.core.logging import get_logger
from martin.speech.whispercpp_backend import WhisperCppBackend, resample

log = get_logger("martin.speech.pipeline")

SAMPLE_RATE = 16000


class Stage(str, Enum):
    """Jednotlivé fáze hlasového zpracování."""

    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SYNTHESIZING = "synthesizing"
    SPEAKING = "speaking"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class VoiceTimings:
    """Naměřené časy jednotlivých fází (v sekundách)."""

    mic_activation_s: float = 0.0
    record_duration_s: float = 0.0
    stt_s: float = 0.0
    llm_first_token_s: float = 0.0
    llm_total_s: float = 0.0
    tts_init_s: float = 0.0
    tts_synth_s: float = 0.0
    playback_start_s: float = 0.0
    end_to_end_s: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "mic_activation_s": round(self.mic_activation_s, 3),
            "record_duration_s": round(self.record_duration_s, 3),
            "stt_s": round(self.stt_s, 3),
            "llm_first_token_s": round(self.llm_first_token_s, 3),
            "llm_total_s": round(self.llm_total_s, 3),
            "tts_init_s": round(self.tts_init_s, 3),
            "tts_synth_s": round(self.tts_synth_s, 3),
            "playback_start_s": round(self.playback_start_s, 3),
            "end_to_end_s": round(self.end_to_end_s, 3),
        }

    def summary(self) -> str:
        """Krátký lidsky čitelný souhrn."""
        return (
            f"mikrofon {self.mic_activation_s * 1000:.0f} ms | "
            f"nahrávání {self.record_duration_s:.1f} s | "
            f"STT {self.stt_s:.2f} s | "
            f"LLM první token {self.llm_first_token_s:.2f} s | "
            f"LLM celkem {self.llm_total_s:.2f} s | "
            f"TTS {self.tts_synth_s:.2f} s | "
            f"přehrávání start {self.playback_start_s:.2f} s | "
            f"celkem {self.end_to_end_s:.2f} s"
        )


@dataclass
class VoiceEvent:
    """Událost z voice pipeline - předávaná do UI přes signály."""

    stage: Stage
    message: str = ""
    text: str = ""
    timings: VoiceTimings = field(default_factory=VoiceTimings)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class VoicePipeline:
    """Řídí hlasový vstup a výstup bez blokování GUI vlákna.

    Všechny těžké operace (nahrávání, STT, syntéza, přehrávání) běží
    v pracovních vláknech. GUI se dozví přes signály.
    """

    def __init__(
        self,
        stt: WhisperCppBackend,
        recorder_factory: Callable[[], Any],
        tts: Any | None = None,
    ) -> None:
        self._stt = stt
        self._recorder_factory = recorder_factory
        self._tts = tts
        self._lock = threading.RLock()
        self._record_thread: threading.Thread | None = None
        self._stop_record = threading.Event()
        self._recorder: Any | None = None
        self._recording = False
        self._timings = VoiceTimings()
        self._cycle_start = 0.0
        self._cancelled = False
        self._on_event: Callable[[VoiceEvent], None] | None = None
        self._on_text: Callable[[str], None] | None = None
        self._audio: np.ndarray | None = None

    # -- konfigurace ---------------------------------------------------
    def set_callbacks(
        self,
        on_event: Callable[[VoiceEvent], None] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> None:
        self._on_event = on_event
        self._on_text = on_text

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def timings(self) -> VoiceTimings:
        with self._lock:
            return VoiceTimings(**vars(self._timings))

    def _emit(
        self,
        stage: Stage,
        message: str = "",
        text: str = "",
        diagnostics: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        event = VoiceEvent(
            stage=stage,
            message=message,
            text=text,
            timings=self.timings,
            diagnostics=diagnostics or {},
            error=error,
        )
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001
                pass

    # -- nahrávání -----------------------------------------------------
    def start_recording(self) -> bool:
        """Zapne nahrávání. Vrací True při úspěchu.

        Samotné otevření zařízení je rychlé, ale i tak se dělá v
        pracovním vlákně, aby GUI nikdy nečekalo na ovladač zvuku.
        """
        with self._lock:
            if self._record_thread is not None and self._record_thread.is_alive():
                return self._recording
            self._recording = True
            self._cancelled = False
            self._timings = VoiceTimings()
            self._stop_record.clear()
            self._audio = None
            self._stt.reset_cancel()

        start = time.perf_counter()

        def run() -> None:
            recorder = None
            try:
                recorder = self._recorder_factory()
                if not recorder.start():
                    with self._lock:
                        self._recording = False
                    self._emit(
                        Stage.ERROR,
                        error="Mikrofon se nepodařilo otevřít.",
                    )
                    return
                with self._lock:
                    self._recorder = recorder
                    self._timings.mic_activation_s = time.perf_counter() - start
                if not self._stop_record.is_set():
                    self._emit(Stage.RECORDING, message="Poslouchám...")
                # One owner opens AND closes the stream. A cancelled late
                # open must still be closed, never published to another cycle.
                if not self._stop_record.wait(60):
                    self._emit(Stage.ERROR, error="Nahrávání ukončeno po 60 sekundách.")
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._recording = False
                self._emit(
                    Stage.ERROR,
                    error=f"Mikrofon se nepodařilo zapnout: {exc}",
                )
            finally:
                if recorder is not None:
                    try:
                        audio = recorder.stop()
                        rate = getattr(recorder, "sample_rate", SAMPLE_RATE)
                        audio = resample(audio, rate, SAMPLE_RATE)
                        with self._lock:
                            self._audio = audio
                            self._timings.record_duration_s = len(audio) / SAMPLE_RATE
                    except Exception:
                        log.exception("Uvolnění mikrofonu selhalo")
                with self._lock:
                    self._recorder = None
                    self._recording = False

        thread = threading.Thread(target=run, name="martin-mic-open", daemon=True)
        with self._lock:
            self._record_thread = thread
        thread.start()
        return True

    def stop_recording(self) -> np.ndarray | None:
        """Zastaví nahrávání a vrátí zaznamenané audio."""
        with self._lock:
            thread = self._record_thread
            self._recording = False
            self._stop_record.set()
        if thread is None:
            return None
        if thread is not threading.current_thread():
            thread.join(timeout=10)
        if thread.is_alive():
            self._emit(Stage.ERROR, error="Zvukový ovladač neodpovídá při zavírání mikrofonu.")
            return None
        with self._lock:
            audio, self._audio = self._audio, None
            return audio

    def cancel(self) -> None:
        """Zruší aktuální hlasový cyklus."""
        with self._lock:
            self._cancelled = True
        self._stop_record.set()
        with self._lock:
            self._recording = False
        try:
            self._stt.cancel()
        except Exception:  # noqa: BLE001
            pass
        if self._tts is not None:
            try:
                self._tts.stop()
            except Exception:  # noqa: BLE001
                pass
        self._emit(Stage.CANCELLED, message="Zrušeno.")

    def shutdown(self) -> None:
        self.cancel()
        self.stop_recording()

    def update_timings(self, **values: float) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self._timings, key, value)

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    # -- rozpoznávání ---------------------------------------------------
    def transcribe(self, audio: np.ndarray) -> tuple[str, dict[str, Any]]:
        """Rozpozná text z audia (blokující - volat z vlákna).

        Vrací (text, diagnostika). Prázdný text znamená, že požadavek
        se NEPOSÍLÁ - ticho nesmí vymyslet požadavek.
        """
        start = time.perf_counter()
        if self.is_cancelled():
            return "", {"error": "Rozpoznání zrušeno."}
        try:
            outcome = self._stt.transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._timings.stt_s = time.perf_counter() - start
            return "", {"error": f"Rozpoznání řeči selhalo: {exc}"}
        with self._lock:
            self._timings.stt_s = time.perf_counter() - start
        return ("" if self.is_cancelled() else outcome.text), outcome.to_dict()

    def process_recording(self, audio: np.ndarray) -> str:
        """Celý proces od nahrávání k textu.

        Vrací rozpoznaný text, nebo prázdný řetězec když je nahrávka
        neplatná (ticho, šum, halucinace).
        """
        self._emit(Stage.TRANSCRIBING, message="Rozpoznávám řeč...")
        text, diagnostics = self.transcribe(audio)
        if not text:
            reason = diagnostics.get("diagnostics", {}).get("rejected_reason", "")
            self._emit(
                Stage.ERROR,
                message="Nic jsem neslyšel.",
                diagnostics=diagnostics,
                error=reason,
            )
            return ""
        self._emit(Stage.TRANSCRIBING, message=f"Rozpoznáno: {text}", text=text)
        return text
