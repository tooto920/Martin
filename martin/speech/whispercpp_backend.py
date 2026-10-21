"""Backend pro rozpoznávání řeči přes whisper.cpp (pywhispercpp).

Proč whisper.cpp a ne faster-whisper:
  faster-whisper potřebuje PyAV (`av/logging.pyd`), který na tomto
  počítači blokuje zásada zabezpečení Windows (WDAC). whisper.cpp
  používá vlastní nativní knihovnu, která zásadou není dotčena, a
  navíc má vestavěný Silero VAD, který odfiltruje ticho - a tím
  zabrání tomu, aby Whisper vymýšlel text v tichu.

Vlastnosti:
  * Model se načítá lazily a zůstává v paměti (další použití je rychlé).
  * Vestavěný Silero VAD - ticho nevytvoří žádný segment.
  * Prah RMS - ticho a šum se odfiltrují už před Whisperem.
  * Podporuje zrušení během inference.
  * Diagnostické metadata (bez raw audia).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from martin.core.logging import get_logger

log = get_logger("martin.speech.whispercpp_backend")

SAMPLE_RATE = 16000

# Rucni prah RMS - pod tim je signalu považovano za ticho.
#
# Dulezite: hlavni obrana proti halucinacim je vestaveny Silero VAD
# whisper.cpp (ten rozpoznal i realny sum mikrofonu - 0 segmentu).
# RMS prah je jen hrana rychleho odmictnuti, proto je nizky, aby
# neodmital tichou reč.
DEFAULT_SILENCE_RMS = 0.0008
# Delka minimalniho uspechneho prepisu.
MIN_TRANSCRIPT_CHARS = 2
# Vsechny tyhle vety whisper vymysli ze ticha - je to tzv. hallucination.
KNOWN_HALLUCINATIONS = (
    "když to je výtěl",
    "když to je výtěl, že to je výtěl",
    "děkuji za pozornost",
    "děkujeme za pozornost",
    "subtitles by the amara org community",
    "překladatel",
    "amara.org",
    "www.amara.org",
    "děkuji za sledování",
    "přehráno",
    "you",
    "bye.",
    "thanks for watching!",
    "thank you.",
)


@dataclass(slots=True)
class SttDiagnostics:
    """Bezpecna diagnostika transformace (bez raw audia)."""

    backend: str = ""
    audio_duration_s: float = 0.0
    audio_rms: float = 0.0
    speech_ratio: float = 0.0
    segment_count: int = 0
    model_load_s: float = 0.0
    transcribe_s: float = 0.0
    total_s: float = 0.0
    rejected_reason: str = ""
    text_len: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "audio_duration_s": round(self.audio_duration_s, 3),
            "audio_rms": round(self.audio_rms, 5),
            "speech_ratio": round(self.speech_ratio, 3),
            "segment_count": self.segment_count,
            "model_load_s": round(self.model_load_s, 3),
            "transcribe_s": round(self.transcribe_s, 3),
            "total_s": round(self.total_s, 3),
            "rejected_reason": self.rejected_reason,
            "text_len": self.text_len,
            **self.extra,
        }


@dataclass(slots=True)
class TranscriptionOutcome:
    """Vysledek rozpoznani reči."""

    text: str
    ok: bool
    error: str = ""
    diagnostics: SttDiagnostics = field(default_factory=SttDiagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "ok": self.ok,
            "error": self.error,
            "diagnostics": self.diagnostics.to_dict(),
        }


class WhisperCppBackend:
    """Rozpoznání řeči přes whisper.cpp (pywhispercpp)."""

    def __init__(
        self,
        model_size: str = "small",
        models_dir: str | Path | None = None,
        n_threads: int = 4,
        language: str = "cs",
        vad_model_path: str | Path | None = None,
        silence_rms: float = DEFAULT_SILENCE_RMS,
    ) -> None:
        self._model_size = model_size
        self._models_dir = Path(models_dir) if models_dir else None
        self._n_threads = n_threads
        self._language = language
        self._vad_model_path = Path(vad_model_path) if vad_model_path else None
        self._silence_rms = silence_rms
        self._model: Any | None = None
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()
        self._cancel = threading.Event()
        self._last_load_s = 0.0
        self._inference_lock = threading.RLock()

    # -- konfigurace ---------------------------------------------------
    @property
    def model_size(self) -> str:
        return self._model_size

    @property
    def language(self) -> str:
        return self._language

    def set_model(self, model_size: str) -> None:
        """Změní model - načte se při příštím použití."""
        with self._inference_lock, self._lock:
            if model_size != self._model_size:
                self._model_size = model_size
                self._model = None

    def set_language(self, language: str) -> None:
        with self._inference_lock, self._lock:
            self._language = language
            self._model = None

    def set_silence_threshold(self, threshold: float) -> None:
        with self._lock:
            self._silence_rms = max(0.0, float(threshold))

    def cancel(self) -> None:
        """Zrusi probihajici inferenci."""
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    # -- dostupnost ----------------------------------------------------
    @staticmethod
    def backend_available() -> bool:
        """Je pywhispercpp importovatelny?"""
        try:
            import pywhispercpp

            _ = pywhispercpp

            return True
        except Exception:  # noqa: BLE001
            return False

    def model_file(self) -> Path | None:
        """Cesta k .bin souboru modelu."""
        if self._models_dir is None:
            return None
        candidate = self._models_dir / f"ggml-{self._model_size}.bin"
        return candidate if candidate.is_file() else None

    def vad_file(self) -> Path | None:
        """Cesta k VAD modelu."""
        if self._vad_model_path is None:
            return None
        return self._vad_model_path if self._vad_model_path.is_file() else None

    def is_ready(self) -> bool:
        """Je backend pripravený k pouziti?"""
        return self.model_file() is not None and self.backend_available()

    def status(self) -> dict[str, Any]:
        """Diagnostika dostupnosti backendu."""
        return {
            "backend": "whisper.cpp",
            "available": self.backend_available(),
            "model_size": self._model_size,
            "model_file": str(self.model_file() or ""),
            "model_present": self.model_file() is not None,
            "vad_present": self.vad_file() is not None,
            "language": self._language,
            "silence_rms": self._silence_rms,
            "loaded": self._model is not None,
        }

    # -- model ----------------------------------------------------------
    def _ensure_model(self) -> Any:
        """Nacte model (lazy, thread-safe)."""
        with self._lock:
            if self._model is not None:
                return self._model
        with self._load_lock:
            with self._lock:
                if self._model is not None:
                    return self._model
            start = time.perf_counter()
            try:
                from pywhispercpp.model import Model
            except ImportError as exc:
                raise RuntimeError(
                    "whisper.cpp backend není dostupný - pywhispercpp není "
                    "nainstalován nebo je blokován zásadou zabezpečení."
                ) from exc
            model_file = self.model_file()
            if model_file is None:
                raise RuntimeError(
                    f"Model whisper.cpp '{self._model_size}' není nalezen "
                    f"({self._models_dir})."
                )
            log.info("Nacitam whisper.cpp model %s", model_file)
            model = Model(
                self._model_size,
                models_dir=str(self._models_dir),
                n_threads=self._n_threads,
                language=self._language,
                print_realtime=False,
                print_progress=False,
            )
            self._last_load_s = time.perf_counter() - start
            with self._lock:
                self._model = model
            return model

    def warm_up(self) -> bool:
        """Nacte model dopredu, aby prvni povel byla rychla.

        Volat z vlakna - nikdy z GUI vlakna.
        """
        try:
            with self._inference_lock:
                self._ensure_model()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Warm-up whisper.cpp selhal: %s", exc)
            return False

    def unload(self) -> None:
        """Uvolni model z pameti."""
        with self._inference_lock, self._lock:
            self._model = None

    # -- rozpoznavani ---------------------------------------------------
    def transcribe(
        self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE,
    ) -> TranscriptionOutcome:
        # pywhispercpp keeps mutable decoding parameters and a single native
        # context. Do not infer or unload concurrently on this context.
        with self._inference_lock:
            return self._transcribe(audio, sample_rate)

    def _transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
    ) -> TranscriptionOutcome:
        """Rozpozná text z audia.

        Ticho a nízkoenergetický šum se odfiltrují PŘED Whisperem,
        takže tichá nahrávka nemůže vyprodukovat vymyšlený požadavek.
        """
        diagnostics = SttDiagnostics(backend="whisper.cpp")
        start = time.perf_counter()

        if audio is None or len(audio) == 0:
            diagnostics.rejected_reason = "prázdné audio"
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome("", False, "Prázdné audio.", diagnostics)

        data = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sample_rate <= 0 or not np.all(np.isfinite(data)) or np.max(np.abs(data)) > 1.01:
            diagnostics.rejected_reason = "neplatné audio"
            return TranscriptionOutcome("", False, "Neplatná zvuková data.", diagnostics)
        if self._cancel.is_set():
            return TranscriptionOutcome("", False, "Rozpoznání zrušeno.", diagnostics)
        if sample_rate and sample_rate != SAMPLE_RATE:
            data = resample(data, sample_rate, SAMPLE_RATE)

        diagnostics.audio_duration_s = len(data) / float(SAMPLE_RATE)
        rms = float(np.sqrt(np.mean(np.square(data))))
        diagnostics.audio_rms = rms

        # 1) Ticho - rychlá kontrola RMS. Hlavní filtr je Silero VAD
        #    v kroku 2, ktery rozezná i tichou řeč od šumu.
        if rms < self._silence_rms:
            diagnostics.rejected_reason = (
                f"ticho (rms {rms:.5f} < {self._silence_rms:.5f})"
            )
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome(
                "", False, "Zaznamenal se jen tichý zvuk.", diagnostics
            )

        # 2) Vestavěny Silero VAD whisper.cpp - ticho neprodukuje segmenty.
        vad_path = self.vad_file()
        use_vad = vad_path is not None
        if use_vad:
            try:
                import _pywhispercpp

                _ = _pywhispercpp

            except Exception:  # noqa: BLE001
                use_vad = False

        try:
            model = self._ensure_model()
        except RuntimeError as exc:
            diagnostics.rejected_reason = "backend nedostupný"
            diagnostics.model_load_s = self._last_load_s
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome("", False, str(exc), diagnostics)

        diagnostics.model_load_s = self._last_load_s

        transcribe_start = time.perf_counter()
        try:
            if use_vad:
                segments = model.transcribe(
                    data, vad=True, vad_model_path=str(vad_path),
                    language=self._language if self._language != "auto" else "",
                    no_context=True, abort_callback=self._cancel.is_set,
                )
            else:
                # Noise must never become an executable desktop command when
                # the speech detector is missing.
                diagnostics.rejected_reason = "chybí VAD"
                return TranscriptionOutcome("", False, "Chybí model VAD pro bezpečné rozpoznání.", diagnostics)
        except Exception as exc:  # noqa: BLE001
            diagnostics.rejected_reason = "chyba transkripce"
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome(
                "", False, f"Rozpoznání řeči selhalo: {exc}", diagnostics
            )
        finally:
            diagnostics.transcribe_s = time.perf_counter() - transcribe_start

        if self._cancel.is_set():
            diagnostics.rejected_reason = "zrušeno"
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome("", False, "Rozpoznání zrušeno.", diagnostics)

        diagnostics.segment_count = len(segments) if segments else 0
        text = " ".join(
            str(getattr(s, "text", "")).strip() for s in (segments or [])
        ).strip()
        text = _cleanup(text)
        diagnostics.text_len = len(text)

        # 3) Prazdny prepis.
        if not text:
            diagnostics.rejected_reason = "prázdný přepis (VAD odfiltroval ticho)"
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome(
                "", False, "Rozpoznání řeči nevrátilo žádný text.", diagnostics
            )

        # 4) Znama halucinace - text, ktery whisper vymysli ze ticha.
        lowered = text.lower().strip(" .!,")
        if lowered in {h.lower() for h in KNOWN_HALLUCINATIONS}:
            diagnostics.rejected_reason = "rozpoznána známá halucinace"
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome(
                "", False, "Rozpoznaný text vypadal jako neplatný.", diagnostics
            )

        if len(text) < MIN_TRANSCRIPT_CHARS:
            diagnostics.rejected_reason = "příliš krátký text"
            diagnostics.total_s = time.perf_counter() - start
            return TranscriptionOutcome(
                "", False, "Rozpoznání řeči nevrátilo žádný text.", diagnostics
            )

        diagnostics.total_s = time.perf_counter() - start
        return TranscriptionOutcome(text, True, "", diagnostics)


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Převzorkuje audio (lineární interpolace)."""
    if source_rate == target_rate or len(audio) == 0:
        return np.asarray(audio, dtype=np.float32)
    target_length = int(round(len(audio) * target_rate / float(source_rate)))
    if target_length <= 0:
        return np.array([], dtype=np.float32)
    source_positions = np.linspace(0.0, len(audio) - 1, num=len(audio))
    target_positions = np.linspace(0.0, len(audio) - 1, num=target_length)
    return np.interp(
        target_positions, source_positions, np.asarray(audio, dtype=np.float32)
    ).astype(np.float32)


def _cleanup(text: str) -> str:
    """Vycisti prepis - odstrani opakujici se fraze a nadbytecne mezery.

    Whisper obcas opakuje stejnou frazi nekolikrat za sebou
    (typicky pri tichu nebo sumu). Opakovany CELE BLOK se zredukuje
    na jednu kopii. Castne opakovani (A B A B) zustava, protoze to
    muze byt skutecne zreknuta veta.
    """
    if not text:
        return ""
    text = " ".join(text.split())
    words = text.split()
    if len(words) < 2:
        return text

    changed = True
    while changed:
        changed = False
        for block_size in range(min(4, len(words) // 2), 0, -1):
            index = 0
            result: list[str] = []
            while index < len(words):
                block = words[index : index + block_size]
                if len(block) == block_size:
                    nxt = words[index + block_size : index + 2 * block_size]
                    if nxt == block:
                        # Stejny blok hned znova - preskocime duplikat.
                        index += block_size
                        changed = True
                        continue
                result.extend(block)
                index += block_size
            words = result
            if changed:
                break

    return " ".join(words).strip()
