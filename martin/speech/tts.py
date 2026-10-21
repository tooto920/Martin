"""Syntéza řeči přes Piper - plně offline, s českými hlasy.

Piper běží jako podproces přes `piper` CLI (případně `python -m piper`).
Přehrávání zajišťuje sounddevice, takže lze přehrávání kdykoli přerušit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from martin.core.logging import get_logger
from martin.paths import find_piper_voice

log = get_logger("martin.speech.tts")


@dataclass(slots=True)
class TTSResult:
    """Výsledek syntézy."""

    ok: bool
    text: str = ""
    audio_path: str = ""
    duration_s: float = 0.0
    error: str = ""


class PiperTTS:
    """Syntéza české řeči pomocí Piper."""

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
        self._stream: Any | None = None
        self._playing = False
        self._stop_event = threading.Event()

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
        self._voice = voice

    def set_output_device(self, device: str) -> None:
        self._output_device = device

    def available(self) -> bool:
        """Je Piper použitelný?"""
        return self.voice_path() is not None and self._piper_command() is not None

    def voice_path(self) -> Path | None:
        """Cesta k .onnx modelu hlasu."""
        return find_piper_voice(self._voice) or find_piper_voice()

    def available_voices(self) -> list[str]:
        """Seznam dostupných českých hlasů."""
        from martin.paths import PIPER_VOICES_DIR

        if not PIPER_VOICES_DIR.is_dir():
            return []
        return sorted(p.stem for p in PIPER_VOICES_DIR.glob("*.onnx"))

    @staticmethod
    def _piper_command() -> list[str] | None:
        """Najde způsob spuštění Piperu (seznam argumentů).

        Hledá postupně: piper v PATH, piper v adresáři aplikace/venv,
        pak python -m piper.
        """
        direct = shutil.which("piper")
        if direct:
            return [direct]

        candidates = []
        # Vedle spustitelného souboru aplikace (PyInstaller onedir).
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).parent / "piper.exe")
        else:
            # Adresář skriptu venvu - obvykle .venv/Scripts.
            candidates.append(Path(sys.executable).parent / "piper.exe")
            candidates.append(Path(__file__).resolve().parent.parent.parent / ".venv" / "Scripts" / "piper.exe")

        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate)]

        return [sys.executable, "-m", "piper"]

    # -- syntéza -------------------------------------------------------
    def synthesize(self, text: str) -> TTSResult:
        """Vygeneruje WAV soubor z textu."""
        text = (text or "").strip()
        if not text:
            return TTSResult(ok=False, error="Prázdný text.")

        voice = self.voice_path()
        if voice is None:
            return TTSResult(ok=False, error="Není dostupný žádný český Piper hlas.")

        command = self._piper_command()
        if command is None:
            return TTSResult(ok=False, error="Piper není nainstalován.")

        out_path = Path(
            os.environ.get("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))
        ) / f"martin_tts_{os.getpid()}_{threading.get_ident()}.wav"

        args = [*command, "--model", str(voice), "--output_file", str(out_path)]
        if abs(self._rate - 1.0) > 0.01:
            args += ["--length_scale", f"{1.0 / self._rate:.3f}"]

        try:
            result = subprocess.run(
                args,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return TTSResult(ok=False, error=f"Syntéza selhala: {exc}")

        if result.returncode != 0 or not out_path.is_file():
            stderr = result.stderr.decode("utf-8", errors="ignore")[:300]
            return TTSResult(ok=False, error=f"Piper selhal: {stderr or result.returncode}")

        duration = self._wav_duration(out_path)
        return TTSResult(
            ok=True,
            text=text,
            audio_path=str(out_path),
            duration_s=duration,
        )

    def speak(self, text: str) -> TTSResult:
        """Syntéza a přehrání. Přehrávání je přerušitelné."""
        result = self.synthesize(text)
        if not result.ok:
            return result
        self.play_file(result.audio_path)
        return result

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

        with self._lock:
            self._stop_event.clear()
            self._playing = True
        try:
            with sd.OutputStream(
                samplerate=samplerate,
                channels=channels,
                dtype="int16",
                device=device,
            ) as stream:
                self._stream = stream
                # sounddevice s int16 streamem chce numpy pole, ne raw bytes.
                samples = np.frombuffer(frames, dtype=np.int16)
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
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.abort()
            except Exception:  # noqa: BLE001
                pass
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def is_playing(self) -> bool:
        return self._playing

    def summarize_for_speech(self, text: str, max_chars: int = 400) -> str:
        """Zkrácí dlouhou odpověď na mluvitelný souhrn."""
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= max_chars:
            return cleaned
        cut = cleaned[:max_chars]
        for marker in (". ", "! ", "? "):
            index = cut.rfind(marker)
            if index > max_chars * 0.4:
                return cut[: index + 1]
        return cut.rstrip() + "..."

    @staticmethod
    def _wav_duration(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() / float(wav.getframerate() or 1)
        except (OSError, wave.Error):
            return 0.0

    def model_info(self) -> dict[str, Any]:
        """Informace o použitém hlasu."""
        voice = self.voice_path()
        info: dict[str, Any] = {
            "available": self.available(),
            "voice": self._voice,
            "rate": self._rate,
            "voices": self.available_voices(),
        }
        if voice is not None:
            info["model_path"] = str(voice)
            info["size_mb"] = round(voice.stat().st_size / (1024 * 1024), 1)
        return info