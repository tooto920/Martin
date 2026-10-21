"""Rozpoznávání české řeči přes faster-whisper.

Podporuje:
  * Czech + anglické technické termíny
  * push-to-talk i nepřetržitý režim
  * VAD (Silero) pro detekci řeči
  * volitelný wake word
  * příkazy pro přerušení

Model se načítá lazy a běží v jednom pracovním vlákně, aby se GUI
neblokovalo.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from martin.core.logging import get_logger

log = get_logger("martin.speech.stt")

SAMPLE_RATE = 16000
FRAME_SIZE = 1600  # 100 ms

# Příkazy, kterými uživatel přeruší mluvení nebo běžící akci.
INTERRUPT_COMMANDS = (
    "zastav",
    "zastavit",
    "stop",
    "ticho",
    "mlč",
    "zastav mluvit",
    "přestaň mluvit",
    "zastav řeč",
    "ok stop",
    "halt",
)


@dataclass(slots=True)
class TranscriptionResult:
    """Výsledek rozpoznání řeči."""

    text: str
    language: str = "cs"
    duration_s: float = 0.0
    confidence: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text.strip()) and not self.error


class WhisperSTT:
    """Rozpoznávání řeči pomocí faster-whisper."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "cs",
        model_path: str | None = None,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model_path = model_path
        self._model: Any | None = None
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()

    @property
    def model_size(self) -> str:
        return self._model_size

    @property
    def language(self) -> str:
        return self._language

    def set_model(self, model_size: str) -> None:
        """Změní velikost modelu (načte se při příštím použití)."""
        with self._lock:
            if model_size != self._model_size:
                self._model_size = model_size
                self._model = None

    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        try:
            import torch  # type: ignore

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001
            return "cpu"

    def _ensure_model(self) -> Any:
        """Načte model (lazy, thread-safe)."""
        with self._lock:
            if self._model is not None:
                return self._model
        with self._load_lock:
            with self._lock:
                if self._model is not None:
                    return self._model
            try:
                from faster_whisper import WhisperModel  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Knihovna faster-whisper není nainstalována."
                ) from exc
            device = self._resolve_device()
            compute = self._compute_type
            if device == "cuda" and compute == "int8":
                compute = "float16"
            log.info("Načítám Whisper model %s (%s, %s)", self._model_size, device, compute)
            model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute,
                download_root=self._model_path,
            )
            with self._lock:
                self._model = model
            return model

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Rozpozná text z audia (float32 mono 16 kHz)."""
        if audio is None or len(audio) == 0:
            return TranscriptionResult(text="", error="Prázdné audio.")
        try:
            model = self._ensure_model()
        except RuntimeError as exc:
            return TranscriptionResult(text="", error=str(exc))

        try:
            segments, info = model.transcribe(
                audio,
                language=language or self._language,
                task="transcribe",
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                beam_size=1,
            )
            collected = [
                {
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text.strip(),
                }
                for s in segments
            ]
            text = " ".join(part["text"] for part in collected).strip()
            duration = float(getattr(info, "duration", 0.0) or 0.0)
            detected = str(getattr(info, "language", "") or "")
            return TranscriptionResult(
                text=text,
                language=detected or (language or self._language),
                duration_s=duration,
                segments=collected,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Rozpoznání řeči selhalo: %s", exc)
            return TranscriptionResult(text="", error=f"Rozpoznání selhalo: {exc}")

    def is_interrupt(self, text: str) -> bool:
        """Zjistí, zda text obsahuje příkaz k přerušení."""
        lowered = " ".join((text or "").lower().split())
        return any(command in lowered for command in INTERRUPT_COMMANDS)

    def contains_wake_word(self, text: str, wake_word: str) -> bool:
        """Zjistí, zda text obsahuje wake word."""
        if not wake_word:
            return False
        lowered = " ".join((text or "").lower().split())
        target = " ".join(wake_word.lower().split())
        return target in lowered


class AudioRecorder:
    """Zachycuje zvuk z mikrofonu po částech."""

    def __init__(self, device: str | int | None = None, sample_rate: int = SAMPLE_RATE) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._stream: Any | None = None
        self._buffer: list[np.ndarray] = []
        self._lock = threading.RLock()
        self._active = False

    def list_devices(self) -> list[dict[str, Any]]:
        """Seznam vstupních zařízení."""
        try:
            import sounddevice as sd  # type: ignore

            devices = sd.query_devices()
            return [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "default_samplerate": d.get("default_samplerate"),
                }
                for d in devices
                if d["max_input_channels"] > 0
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("Výpis zařízení selhal: %s", exc)
            return []

    def start(self) -> bool:
        """Zapne nahrávání."""
        with self._lock:
            if self._active:
                return True
            try:
                import sounddevice as sd  # type: ignore
            except ImportError:
                log.error("sounddevice není nainstalován.")
                return False

            def callback(indata, frames, time_info, status):  # noqa: ARG001
                if status:
                    log.debug("Audio status: %s", status)
                with self._lock:
                    self._buffer.append(indata.copy().reshape(-1))

            try:
                self._stream = sd.InputStream(
                    device=self._device,
                    channels=1,
                    samplerate=self._sample_rate,
                    blocksize=FRAME_SIZE,
                    dtype="float32",
                    callback=callback,
                )
                self._stream.start()
            except Exception as exc:  # noqa: BLE001
                log.error("Zapnutí mikrofonu selhalo: %s", exc)
                self._stream = None
                return False
            self._buffer.clear()
            self._active = True
            return True

    def stop(self) -> np.ndarray:
        """Zastaví nahrávání a vrátí zaznamenané audio."""
        with self._lock:
            self._active = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:  # noqa: BLE001
                    pass
                self._stream = None
            if not self._buffer:
                return np.array([], dtype=np.float32)
            audio = np.concatenate(self._buffer).astype(np.float32)
            self._buffer.clear()
            return audio

    @property
    def active(self) -> bool:
        return self._active

    def is_speaking(self, threshold: float = 0.02) -> bool:
        """Jednoduchá detekce aktivity hlasu (RMS)."""
        with self._lock:
            if not self._buffer:
                return False
            recent = self._buffer[-3:]
            if not recent:
                return False
            chunk = np.concatenate(recent)
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            return rms > threshold


class SileroVAD:
    """Detekce hlasové aktivity přes Silero VAD (ONNX).

    Pokud není model dostupný, použije se energetický detektor jako
    záloha - aplikace pak hlásí, že používá záložní režim.
    """

    def __init__(self, model_path: str | None = None, threshold: float = 0.5) -> None:
        self._model_path = model_path
        self._threshold = threshold
        self._session: Any | None = None
        self._available = False

    def load(self) -> bool:
        """Načte ONNX model. Vrací True při úspěchu."""
        if not self._model_path or not Path(self._model_path).is_file():
            return False
        try:
            import onnxruntime  # type: ignore

            self._session = onnxruntime.InferenceSession(
                self._model_path, providers=["CPUExecutionProvider"]
            )
            self._available = True
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("Silero VAD není dostupný: %s", exc)
            self._available = False
            return False

    @property
    def available(self) -> bool:
        return self._available

    def is_speech(self, audio: np.ndarray) -> bool:
        """Detekuje, zda audio obsahuje řeč."""
        if audio is None or len(audio) == 0:
            return False
        if self._available and self._session is not None:
            try:
                tensor = audio.reshape(1, -1).astype(np.float32)
                inputs = {
                    inp.name: tensor for inp in self._session.get_inputs()
                }
                outputs = self._session.run(None, inputs)
                return float(outputs[0].squeeze()) > self._threshold
            except Exception as exc:  # noqa: BLE001
                log.debug("VAD inference selhal: %s", exc)
        # Záloha: energetický detektor.
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
        return rms > 0.02