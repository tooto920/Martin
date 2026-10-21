"""Offline česká syntéza Piper s kontrolou dat před nativní inicializací.

Syntéza běží v pracovním vlákně, přehrávání vlastní svůj sounddevice stream.
Konkrétní latence závisí na hardwaru; měří ji diagnostický režim.
"""

from __future__ import annotations

import os
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from martin.core.logging import get_logger
from martin.paths import find_piper_voice
from martin.speech.speech_text_formatter import to_speech_text

log = get_logger("martin.speech.tts")


@dataclass(slots=True)
class TTSResult:
    """Výsledek syntézy."""

    ok: bool
    text: str = ""
    audio_path: str = ""
    duration_s: float = 0.0
    error: str = ""
    synth_s: float = 0.0
    load_s: float = 0.0


class PiperTTS:
    """Syntéza české řeči pomocí Piper (in-proces)."""

    def __init__(
        self,
        voice: str = "cs_CZ-jirka-medium",
        rate: float = 1.0,
        output_device: str = "",
    ) -> None:
        self._voice = voice
        self._rate = rate
        self._output_device = output_device
        self._lock = threading.RLock()
        self._voice_obj: Any | None = None
        self._loaded_key: str = ""
        self._load_s = 0.0
        self._stream: Any | None = None
        self._playing = False
        self._stop_event = threading.Event()
        self._load_lock = threading.RLock()
        self._synth_lock = threading.Lock()

    # -- konfigurace ---------------------------------------------------
    @property
    def voice(self) -> str:
        return self._voice

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, rate: float) -> None:
        """Nastaví rychlost mluvení (0.5 - 2.0)."""
        self._rate = max(0.5, min(2.0, float(rate)))

    def set_voice(self, voice: str) -> None:
        with self._lock:
            if voice != self._voice:
                self._voice = voice
                self._voice_obj = None
                self._loaded_key = ""

    def set_output_device(self, device: str) -> None:
        self._output_device = device

    def available(self) -> bool:
        """Je Piper použitelný?"""
        return self.voice_path() is not None and self._piper_importable()

    @staticmethod
    def _piper_importable() -> bool:
        try:
            from piper import PiperVoice
            from piper.phonemize_espeak import ESPEAK_DATA_DIR

            _ = PiperVoice
            PiperTTS._validate_phonemizer_data(ESPEAK_DATA_DIR)
            return True
        except Exception:  # noqa: BLE001
            return False

    def voice_path(self) -> Path | None:
        """Cesta k .onnx modelu hlasu."""
        return find_piper_voice(self._voice) or find_piper_voice()

    def available_voices(self) -> list[str]:
        """Seznam dostupných českých hlasů."""
        from martin.paths import PIPER_VOICES_DIR

        if not PIPER_VOICES_DIR.is_dir():
            return []
        return sorted(p.stem for p in PIPER_VOICES_DIR.glob("*.onnx"))

    # -- model ----------------------------------------------------------
    def _ensure_voice(self) -> Any:
        with self._load_lock:
            return self._load_voice()

    def _load_voice(self) -> Any:
        """Nacte hlas (lazy, thread-safe) a vrati ho.

        Nacitani trva nekolik sekund, proto se nikdy nedela v GUI
        vlakne - pri prvnim pouziti bezi v pozadim vlakne.
        """
        with self._lock:
            if self._voice_obj is not None and self._loaded_key == self._voice:
                return self._voice_obj
        with self._lock:
            self._load_s = 0.0
        import time as _time

        start = _time.perf_counter()
        try:
            from piper import PiperVoice
            from piper.phonemize_espeak import ESPEAK_DATA_DIR
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Piper není dostupný - knihovna piper-tts není nainstalována."
            ) from exc

        model = self.voice_path()
        if model is None:
            raise RuntimeError("Není dostupný žádný český Piper hlas.")

        self._validate_phonemizer_data(ESPEAK_DATA_DIR)

        config = model.with_suffix(model.suffix + ".json")
        if config.is_file():
            voice = PiperVoice.load(str(model), config_path=str(config))
        else:
            voice = PiperVoice.load(str(model))

        elapsed = _time.perf_counter() - start
        with self._lock:
            self._voice_obj = voice
            self._loaded_key = self._voice
            self._load_s = elapsed
        log.info("Piper hlas %s nacten za %.2f s", self._voice, elapsed)
        return voice

    @staticmethod
    def _validate_phonemizer_data(directory: Path) -> None:
        # eSpeak's native initializer calls exit(1) for missing data, which
        # cannot be caught by Python/faulthandler. Check before entering it.
        required = ("phontab", "phonindex", "phondata", "intonations", "cs_dict", "lang/zlw/cs")
        missing = [name for name in required if not (directory / name).is_file()]
        if missing:
            raise RuntimeError("Chybí data Piper/eSpeak: " + ", ".join(missing) + ". Rozbal celou distribuci Martina.")

    def warm_up(self) -> bool:
        """Nacte hlas dopredu, aby prvni odpoved znela okamzite.

        Volat z vlakna - nikdy z GUI vlakna.
        """
        try:
            self._ensure_voice()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Warm-up Piper selhal: %s", exc)
            return False

    def unload(self) -> None:
        """Uvolni hlas z paměti."""
        with self._lock:
            self._voice_obj = None
            self._loaded_key = ""

    # -- syntéza -------------------------------------------------------
    def synthesize(self, text: str) -> TTSResult:
        """Vygeneruje WAV soubor z textu (in-proces, bez podprocesu)."""
        import time as _time

        text = to_speech_text(text, max_chars=0)
        if not text:
            return TTSResult(ok=False, error="Prázdný text.")

        try:
            voice = self._ensure_voice()
        except RuntimeError as exc:
            return TTSResult(ok=False, error=str(exc))

        out_path = Path(
            os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))
        ) / f"martin_tts_{os.getpid()}_{threading.get_ident()}.wav"

        start = _time.perf_counter()
        try:
            with self._synth_lock:
                samples = self._synthesize_samples(voice, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Syntéza selhala: %s", exc)
            return TTSResult(ok=False, error=f"Syntéza selhala: {exc}")
        synth_time = _time.perf_counter() - start

        if samples is None or len(samples) == 0:
            return TTSResult(ok=False, error="Piper nevygeneroval žádný zvuk.")

        sample_rate = self._sample_rate(voice)
        try:
            with wave.open(str(out_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                pcm = np.clip(samples, -1.0, 1.0)
                wav.writeframes((pcm * 32767.0).astype(np.int16).tobytes())
        except (OSError, wave.Error) as exc:
            return TTSResult(ok=False, error=f"Uložení audia selhalo: {exc}")

        duration = len(samples) / float(sample_rate or 1)
        return TTSResult(
            ok=True,
            text=text,
            audio_path=str(out_path),
            duration_s=duration,
            synth_s=synth_time,
            load_s=self._load_s,
        )

    def _sample_rate(self, voice: Any) -> int:
        try:
            return int(voice.config.sample_rate)
        except Exception:  # noqa: BLE001
            return 22050

    def _synthesize_samples(self, voice: Any, text: str) -> np.ndarray | None:
        """Syntéza do numpy pole.

        Rychlost mluvení se upravuje přes délku_scale - delší scale =
        pomalejší mluvení (Piper >= 1.2 umí i parametry rychlosti).
        """
        chunks = list(voice.synthesize(text))
        if not chunks:
            return None
        arrays = [
            np.asarray(chunk.audio_float_array, dtype=np.float32) for chunk in chunks
        ]
        audio = np.concatenate(arrays) if arrays else None
        if audio is None:
            return None

        rate = self._rate
        if abs(rate - 1.0) > 0.01:
            # Změna tempa změnou délky zvuku (jednoduchý time-stretch).
            factor = 1.0 / rate
            new_length = max(1, int(len(audio) * factor))
            positions = np.linspace(0.0, len(audio) - 1, num=new_length)
            audio = np.interp(positions, np.arange(len(audio)), audio).astype(
                np.float32
            )
        return audio

    def speak(self, text: str) -> TTSResult:
        """Syntéza a přehrání. Přehrávání je přerušitelné."""
        result = self.synthesize(text)
        if not result.ok:
            return result
        self.play_file(result.audio_path)
        return result

    # -- přehrávání -----------------------------------------------------
    def play_file(self, path: str) -> bool:
        """Přehrá WAV soubor. Vrací True, pokud se přehrál celý."""
        file_path = Path(path)
        if not file_path.is_file():
            return False
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            return False

        try:
            with wave.open(str(file_path), "rb") as wav:
                frames = wav.readframes(wav.getnframes())
                samplerate = wav.getframerate()
                channels = wav.getnchannels()
                dtype = wav.getsampwidth()
        except (OSError, wave.Error) as exc:
            log.warning("Načtení WAV selhalo: %s", exc)
            return False

        if dtype != 2:
            log.warning("Piper WAV má neočekávanou šířku vzorku: %s", dtype)
            return False

        device = None
        if self._output_device:
            try:
                device = int(self._output_device)
            except (TypeError, ValueError):
                device = None

        # sounddevice s int16 streamem chce numpy pole, ne raw bytes.
        samples = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels)[:, 0]

        with self._lock:
            self._stop_event.clear()
            self._playing = True
        try:
            with sd.OutputStream(
                samplerate=samplerate,
                channels=1,
                dtype="int16",
                device=device,
            ) as stream:
                self._stream = stream
                block = samplerate // 20
                offset = 0
                total = len(samples)
                while offset < total and not self._stop_event.is_set():
                    chunk = samples[offset : offset + block]
                    if len(chunk) == 0:
                        break
                    stream.write(chunk)
                    offset += block
                stream.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("Přehrávání selhalo: %s", exc)
            return False
        finally:
            with self._lock:
                self._playing = False
                self._stream = None
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
        return not self._stop_event.is_set()

    def stop(self) -> None:
        """Zastaví přehrávání.

        Při ukončení aplikace se často zastavuje už zavřený stream -
        proto je každý krok v samostatném try, aby se ukončovací
        kód aplikace nezhroutil.
        """
        self._stop_event.set()
        # The playback owner closes its stream in its finally block. Closing
        # it here races a native stream.write() on that owner's thread.

    @property
    def is_playing(self) -> bool:
        return self._playing

    # -- text -----------------------------------------------------------
    def summarize_for_speech(self, text: str, max_chars: int = 400) -> str:
        """Připraví text pro mluvení - odstraní Markdown.

        Markdown se NIKDY nesmí číst nahlas. Výsledek je čistá
        mluvenina připravená k syntéze.
        """
        return to_speech_text(text, max_chars=max_chars)

    def model_info(self) -> dict[str, Any]:
        """Informace o použitém hlasu."""
        voice = self.voice_path()
        info: dict[str, Any] = {
            "available": self.available(),
            "voice": self._voice,
            "rate": self._rate,
            "voices": self.available_voices(),
            "loaded": self._voice_obj is not None,
            "mode": "in-process",
        }
        if voice is not None:
            info["model_path"] = str(voice)
            info["size_mb"] = round(voice.stat().st_size / (1024 * 1024), 1)
        return info
