"""Streamovaci syntéza reči - Martin začne mluvit dřív, než model dořekne.

Celá odpoveď se syntetizuje po větách. První syntetizovaná věta
se přehrá dřív, než dorazí zbytek odpovědi.

Pravidla:
  * Věty se oddělují po interpunkci, ale ne po každé tečce
    (zkratka "např." nesmí roztrhat větu).
  * Krátké úseky se spojí, aby syntéza nebyla zbytečně častá.
  * Fronta je OMEZENÁ - pokud LLM mluví rychleji, než se přehrává,
    starší věty se zahodí (nebo se přehrá rychleji).
  * Přehrávání jde kdykoli přerušit.
"""

from __future__ import annotations

import re
from pathlib import Path
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from martin.core.logging import get_logger
from martin.speech.speech_text_formatter import to_speech_text

log = get_logger("martin.speech.streaming_tts")

# Minimalni delka vety, aby se nesyntetizovalo po nekolika slovech.
MIN_SENTENCE_CHARS = 25
# Nejvyssi pocet vet ve fronte pred prehravani.
MAX_QUEUE = 4

# Konec vety - za tim se muze ukoncit veta. Tečka za pismenem neni
# konec vety (napr. "p. Král", "tzv.").
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ0-9])")
# Zkratky, ktere nesmí roztrhat vetu.
_ABBREVIATIONS = (
    "např",
    "tj",
    "tzv",
    "atd",
    "resp",
    "popř",
    "odp",
    "str",
    "čís",
    "mstr",
    "ing",
    "jr",
    "sr",
    "phd",
    "etc",
    "vs",
    "max",
    "min",
    "tzn",
    "příp",
)


@dataclass(slots=True)
class SynthesizedChunk:
    """Jedna syntetizovaná část odpovědi."""

    text: str
    samples: np.ndarray
    sample_rate: int
    index: int = 0


class StreamingTTS:
    """Syntéza po větách s frontou a přehráváním.

    Použití:
        streamer = StreamingTTS(tts)
        streamer.push_text("První věta. Druhá věta.")
        streamer.finish()
        streamer.wait()
    """

    def __init__(self, tts: Any, max_queue: int = MAX_QUEUE) -> None:
        self._tts = tts
        self._max_queue = max_queue
        self._lock = threading.RLock()
        self._buffer = ""
        self._queue: list[str] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._done = threading.Event()
        self._error: str = ""
        self._index = 0
        self._first_audio_s: float | None = None
        self._start_time = 0.0
        self._dropped = 0
        self._samples_played = 0
        self._on_playback_start: Any = None
        self._condition = threading.Condition(self._lock)
        self._input_done = False

    # -- stav -----------------------------------------------------------
    @property
    def error(self) -> str:
        return self._error

    @property
    def dropped_sentences(self) -> int:
        """Kolik vet bylo zahozeno, protoze se neprehralo vcas."""
        return self._dropped

    @property
    def time_to_first_audio(self) -> float | None:
        """Cas od push_text do prvni syntetizovane vet (s)."""
        return self._first_audio_s

    # -- konfigurace ---------------------------------------------------
    def set_callbacks(self, on_playback_start: Any = None) -> None:
        """Nastavi callback, ktery se zavola pri zacatku prehrani."""
        self._on_playback_start = on_playback_start

    # -- vstup ----------------------------------------------------------
    def push_text(self, text: str) -> None:
        """Prida text k syntéze - rozdeli ho na vety.

        Prazdne vety se preskakuji, takze text rozdeleny na vice
        casti (streaming) dava stejny vysledek jako cely text.
        """
        if not text or self._stop.is_set() or self._input_done:
            return
        # to_speech_text text orezava - koncova mezera mezi chunky by
        # se ztratila a slova by se slepila ("spustimMicrosoft").
        with self._lock:
            if self._start_time == 0.0:
                self._start_time = time.perf_counter()
            self._buffer += text
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="martin-stream-tts", daemon=True)
                self._thread.start()
        self._extract_sentences(final=False)

    def finish(self) -> None:
        """Ukonci vstup - zpracuje zbytk buffera a spusti prehravani."""
        with self._lock:
            if self._input_done or self._stop.is_set():
                return
        self._extract_sentences(final=True)
        with self._condition:
            self._input_done = True
            if self._thread is None:
                self._done.set()
            self._condition.notify_all()

    def wait(self, timeout: float = 120.0) -> bool:
        """Ceka na dokonceni prehravani."""
        return self._done.wait(timeout=timeout)

    def stop(self) -> None:
        """Zastavi syntézu i prehravani."""
        self._stop.set()
        with self._lock:
            self._queue.clear()
            self._condition.notify_all()
        try:
            self._tts.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._thread is None:
            self._done.set()

    # -- interni --------------------------------------------------------
    def _extract_sentences(self, final: bool) -> None:
        """Rozdeli buffer na vety a naplanuje syntézu."""
        with self._lock:
            buffer = self._buffer
            if not final and "```" in buffer:
                return
            self._buffer = ""
        if not buffer:
            return
        if final and "```" in buffer:
            buffer = to_speech_text(buffer, max_chars=0)
        sentences, leftover = _split_sentences(buffer, final=final)
        with self._lock:
            # Zbytek neukoncene vety se vrati do bufferu. Trailing
            # mezera se NESMI zahodit, jinak se slova slepou.
            if leftover and buffer.endswith(" "):
                leftover += " "
            self._buffer = leftover
        for sentence in sentences:
            if not sentence.strip():
                continue
            if self._stop.is_set():
                return
            with self._condition:
                while len(self._queue) >= self._max_queue and not self._stop.is_set():
                    self._condition.wait(0.1)
                if self._stop.is_set():
                    return
                self._queue.append(sentence)
                self._condition.notify_all()

    def _synthesize(self, sentence: str) -> SynthesizedChunk | None:
        """Syntetizuje jednu vetu (blokujici - bezi ve vlakne)."""
        try:
            sentence = to_speech_text(sentence, max_chars=0)
            if not sentence:
                return None
            result = self._tts.synthesize(sentence)
        except Exception as exc:  # noqa: BLE001
            log.warning("Syntéza věty selhala: %s", exc)
            self._error = str(exc)
            return
        if not result.ok or not result.audio_path:
            if result.error:
                self._error = result.error
            return

        samples, rate = _read_wav(result.audio_path)
        try:
            Path(result.audio_path).unlink(missing_ok=True)
        except OSError:
            pass
        if samples is None or len(samples) == 0:
            return

        chunk = SynthesizedChunk(
            text=sentence,
            samples=samples,
            sample_rate=rate,
            index=self._index,
        )
        self._index += 1
        return chunk

    def _run(self) -> None:
        """Prehraje frontu vet."""
        try:
            while not self._stop.is_set():
                with self._condition:
                    while not self._queue and not self._input_done and not self._stop.is_set():
                        self._condition.wait()
                    if self._stop.is_set() or (not self._queue and self._input_done):
                        break
                    sentence = self._queue.pop(0)
                    self._condition.notify_all()
                chunk = self._synthesize(sentence)
                if chunk is None or self._stop.is_set():
                    continue
                if self._on_playback_start is not None and self._samples_played == 0:
                    try:
                        self._on_playback_start()
                    except Exception:  # noqa: BLE001
                        pass
                self._play(chunk)
        finally:
            self._done.set()

    def _play(self, chunk: SynthesizedChunk) -> None:
        """Přehrá jednu syntetizovanou vetu."""
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            return
        device = None
        out_device = getattr(self._tts, "_output_device", "")
        if out_device:
            try:
                device = int(out_device)
            except (TypeError, ValueError):
                device = None
        try:
            with sd.OutputStream(
                samplerate=chunk.sample_rate, channels=1, dtype="int16", device=device
            ) as stream:
                if self._first_audio_s is None and self._start_time:
                    self._first_audio_s = time.perf_counter() - self._start_time
                block = chunk.sample_rate // 20
                offset = 0
                total = len(chunk.samples)
                while offset < total and not self._stop.is_set():
                    part = chunk.samples[offset : offset + block]
                    if len(part) == 0:
                        break
                    stream.write(part)
                    offset += block
                stream.stop()
            self._samples_played += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Přehrání věty selhalo: %s", exc)
            self._error = str(exc)


def _split_sentences(text: str, final: bool = False) -> list[str]:
    """Rozdeli text na kompletni vety.

    Vraci (vety, zbytek). Zbytek je cast vety, ktera jeste neni
    ukoncena - pri streamingu se k nemu pri dalsim textu prida.
    """
    text = text.strip()
    if not text:
        return [], ""

    parts: list[str] = []
    buffer = ""

    # Rozdeleni na slova POZUCUJICI oddelovacich mezer - mezery se
    # neztrace, takze se da text zase slepit dohromady.
    words = text.split(" ")
    for index, word in enumerate(words):
        buffer += word
        if index < len(words) - 1:
            buffer += " "
        if not _ends_sentence(buffer):
            continue
        candidate = buffer.strip()
        if len(candidate) < MIN_SENTENCE_CHARS and not final:
            # Krátká věta - počkáme na další text, at nesplyne.
            continue
        parts.append(candidate)
        buffer = ""

    # Zbytek si nechava puvodni koncovou mezeru - ta se nesmi ztratit.
    leftover = buffer.rstrip() if not final else buffer.strip()
    if final and leftover:
        parts.append(leftover)
        leftover = ""
    return parts, leftover


def _ends_sentence(text: str) -> bool:
    """Konci veta na interpunkci, ktera neni zkratka?

    "Toto je veta."  -> True
    "napr. to znamena" -> False (zkratka)
    "p. Kral"        -> False (inicial)
    """
    stripped = text.rstrip().rstrip('*_`"”»)]')
    if not stripped:
        return False
    if stripped[-1] not in ".!?":
        return False
    if stripped[-1] == ".":
        # Inicial ("p. Kral") - jedno pismeno pred teckou.
        word = stripped.rsplit(" ", 1)[-1].rstrip(".")
        if len(word) == 1 and word.isalpha():
            return False
        # Zkratka ("napr.") - slovo z kratkeho seznamu.
        if word.lower() in _ABBREVIATIONS:
            return False
    return True


def _is_abbreviation(text: str) -> bool:
    """Konci veta zkratkou (napr. "např." )?"""
    stripped = text.rstrip()
    if not stripped.endswith("."):
        return False
    word = stripped.rsplit(" ", 1)[-1].rstrip(".").lower()
    if not word:
        return False
    if word in _ABBREVIATIONS:
        return True
    # Obecně: jedno pismeno + tečka (initials).
    if len(word) == 1 and word.isalpha():
        return True
    return False


def _read_wav(path: str) -> tuple[np.ndarray | None, int]:
    """Precte WAV soubor a vrati (samples, sample_rate)."""
    import wave
    from pathlib import Path

    file_path = Path(path)
    if not file_path.is_file():
        return None, 22050
    try:
        with wave.open(str(file_path), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
            rate = wav.getframerate()
            channels = wav.getnchannels()
            width = wav.getsampwidth()
    except (OSError, wave.Error):
        return None, 22050
    if width != 2:
        return None, rate
    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels)[:, 0]
    return samples, rate
