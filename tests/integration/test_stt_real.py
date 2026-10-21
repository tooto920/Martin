"""Integrační testy rozpoznávání řeči na REÁLNÉM zvuku.

Používá zvuk syntetizovaný Piperem (reprodukovatelný, ne nahodný)
a reálný mikrofon počítače, pokud je dostupný.

Tyto testy se přeskočí, pokud nejsou modely nebo hardware k dispozici.
"""

from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np
import pytest

from martin.paths import PIPER_VOICES_DIR, WHISPER_MODELS_DIR, WHISPER_VAD_MODEL
from martin.speech.whispercpp_backend import WhisperCppBackend, resample

pytestmark = pytest.mark.integration

# Text, který se má rozpoznat - s diakritikou i anglickým terminem.
PHRASE = "Martine, otevři Microsoft Flight Simulator."


@pytest.fixture(scope="module")
def backend():
    if not WHISPER_MODELS_DIR.is_dir():
        pytest.skip("Modely whisper.cpp nejsou nainstalovány")
    if not any(WHISPER_MODELS_DIR.glob("ggml-*.bin")):
        pytest.skip("Modely whisper.cpp nejsou staženy")
    instance = WhisperCppBackend(
        model_size="small",
        models_dir=WHISPER_MODELS_DIR,
        vad_model_path=WHISPER_VAD_MODEL,
    )
    if not instance.backend_available():
        pytest.skip("pywhispercpp není dostupný")
    return instance


@pytest.fixture(scope="module")
def speech_audio():
    """Syntéza hlasové fráze Piperem - skutečný zvuk, ne mock."""
    voices = sorted(PIPER_VOICES_DIR.glob("*.onnx")) if PIPER_VOICES_DIR.is_dir() else []
    if not voices:
        pytest.skip("Český hlas Piper není dostupný")
    try:
        from piper import PiperVoice
    except Exception:  # noqa: BLE001
        pytest.skip("piper není dostupný")

    model = voices[0]
    config = model.with_suffix(model.suffix + ".json")
    voice = PiperVoice.load(
        str(model), config_path=str(config) if config.is_file() else None
    )
    chunks = list(voice.synthesize(PHRASE))
    if not chunks:
        pytest.skip("Piper nevygeneroval zvuk")
    audio = np.concatenate(
        [np.asarray(c.audio_float_array, dtype=np.float32) for c in chunks]
    )
    rate = int(voice.config.sample_rate)
    return resample(audio, rate, 16000)


class TestRealAudioTranscription:
    def test_speech_is_recognized(self, backend, speech_audio):
        """SKUTECNY ZVUK - Piper syntéza -> whisper.cpp."""
        out = backend.transcribe(speech_audio)
        assert out.ok is True, f"rozpoznání selhalo: {out.error}"
        assert out.text
        # Hledáme klicova slova (diakritika se v prepisu obcas ztraci).
        lowered = out.text.lower()
        assert "martin" in lowered
        assert "flight" in lowered or "simul" in lowered

    def test_transcription_is_fast(self, backend, speech_audio):
        """Rozpoznavani ma byt snesitelne rychle."""
        backend.warm_up()
        t0 = time.perf_counter()
        backend.transcribe(speech_audio)
        elapsed = time.perf_counter() - t0
        assert elapsed < 15.0, f"rozpoznání trvalo {elapsed:.1f} s"

    def test_diagnostics_present(self, backend, speech_audio):
        out = backend.transcribe(speech_audio)
        data = out.diagnostics.to_dict()
        assert data["backend"] == "whisper.cpp"
        assert data["segment_count"] >= 1
        assert data["audio_rms"] > 0
        assert data["total_s"] > 0


class TestSilenceRejection:
    def test_digital_silence_rejected(self, backend):
        out = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert out.ok is False
        assert out.text == ""
        assert out.diagnostics.rejected_reason

    def test_low_level_noise_rejected(self, backend):
        """Sum pod uroveni prahu nesmi vytvorit zadny pozadavek."""
        rng = np.random.default_rng(1234)
        noise = (rng.standard_normal(16000) * 0.0003).astype(np.float32)
        out = backend.transcribe(noise)
        assert out.ok is False
        assert out.text == ""

    def test_microphone_noise_rejected(self, backend):
        """REALNY SUM Z MIKROFONU - nesmi vzniknout halucinace."""
        try:
            import sounddevice as sd
        except Exception:  # noqa: BLE001
            pytest.skip("sounddevice není dostupný")
        try:
            devices = sd.query_devices()
        except Exception:  # noqa: BLE001
            pytest.skip("zvuková zařízení nejsou dostupná")
        inputs = [d for d in devices if d["max_input_channels"] > 0]
        if not inputs:
            pytest.skip("Žádný vstup není dostupný")

        chunks = []

        def callback(indata, frames, time_info, status):
            chunks.append(indata.copy().reshape(-1))

        captured = None
        for device in inputs[:6]:
            try:
                stream = sd.InputStream(
                    device=device["index"],
                    channels=1,
                    samplerate=16000,
                    blocksize=1600,
                    dtype="float32",
                    callback=callback,
                )
                stream.start()
                time.sleep(1.5)
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                continue
            if chunks:
                captured = np.concatenate(chunks).astype(np.float32)
                break
        if captured is None or len(captured) == 0:
            pytest.skip("Mikrofon se nepodařilo otevřít")

        rms = float(np.sqrt(np.mean(np.square(captured))))
        if rms > 0.05:
            pytest.skip("V prostředí je skutečný hlas - test by nebyl deterministický")
        out = backend.transcribe(captured)
        # Ticho nesmi vytvorit text (ani kdyz je sum slysetelny).
        assert out.text == "", f"halucinace ze sumu: {out.text!r}"


class TestModelLoading:
    def test_warm_up_loads_model(self, backend):
        if not backend.model_file():
            pytest.skip("Model není stažen")
        assert backend.warm_up() is True
        assert backend.status()["loaded"] is True

    def test_unload_releases(self, backend):
        backend.warm_up()
        backend.unload()
        assert backend.status()["loaded"] is False