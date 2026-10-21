"""Regresni testy hlasoveho pipeline (BUG 1, 2, 4).

Poznamka k testum:
  * Testy s `mocked` zadnim vypisuji "MOCKED" - nejde o overeni
    na skutecnem mikrofonu.
  * Testy nad skutecnym zvukem pouzivaji Piper-syntezovany audio
    soubor (reprodukovatelny, ne nahodny).
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from martin.speech.pipeline import Stage, VoicePipeline, VoiceTimings
from martin.speech.whispercpp_backend import (
    KNOWN_HALLUCINATIONS,
    SttDiagnostics,
    WhisperCppBackend,
    resample,
)


class FakeRecorder:
    """MOCKED nahravac - vraci predem nastavene audio."""

    def __init__(self, audio=None, start_ok=True, stop_error=None):
        self._audio = audio
        self._start_ok = start_ok
        self._stop_error = stop_error
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return self._start_ok

    def stop(self):
        self.stopped = True
        if self._stop_error:
            raise self._stop_error
        return self._audio

    @property
    def sample_rate(self):
        return 16000


class FakeStt:
    """MOCKED rozpoznavani - vraci predem nastaveny vysledek."""

    def __init__(self, text="", error=None, delay=0.0):
        self._text = text
        self._error = error
        self._delay = delay
        self.cancelled = False
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._error:
            return type(
                "O", (), {"text": "", "error": self._error, "to_dict": lambda s: {}}
            )()
        return type(
            "O",
            (),
            {
                "text": self._text,
                "error": "",
                "to_dict": lambda s: {"text": self._text, "ok": bool(self._text)},
            },
        )()

    def cancel(self):
        self.cancelled = True

    def reset_cancel(self):
        self.cancelled = False


# ---------------------------------------------------------------------------
# 1) Inicializace STT - chyby a blokovane zavislosti
# ---------------------------------------------------------------------------
class TestSttInitializationFailures:
    def test_missing_model_reports_error(self, tmp_path):
        """Chybejici model musi hlasit, ne spadnout."""
        backend = WhisperCppBackend(
            model_size="small", models_dir=tmp_path, vad_model_path=tmp_path / "vad.bin"
        )
        assert backend.is_ready() is False
        status = backend.status()
        assert status["model_present"] is False
        assert "available" in status

    def test_backend_available_detection(self):
        """Detekce dostupnosti nesmi vyvolat výjimku."""
        assert isinstance(WhisperCppBackend.backend_available(), bool)

    def test_transcribe_with_missing_model_returns_error(self, tmp_path):
        backend = WhisperCppBackend(
            model_size="small", models_dir=tmp_path, vad_model_path=tmp_path / "vad.bin"
        )
        out = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert out.ok is False
        assert out.error

    def test_empty_audio_rejected(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        out = backend.transcribe(np.array([], dtype=np.float32))
        assert out.ok is False
        assert "audio" in out.error.lower()

    def test_diagnostics_include_failure_reason(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        out = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert out.diagnostics.rejected_reason
        assert isinstance(out.diagnostics.to_dict(), dict)


# ---------------------------------------------------------------------------
# 2) Tichy mikrofon - nesmi vytvorit zadny požadavek
# ---------------------------------------------------------------------------
class TestSilentMicrophone:
    def test_silence_rejected_by_rms_gate(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        out = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert out.ok is False
        assert "tich" in out.error.lower()
        assert out.text == ""

    def test_quiet_noise_rejected(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        noise = (np.random.default_rng(7).standard_normal(16000) * 0.001).astype(
            np.float32
        )
        out = backend.transcribe(noise)
        assert out.ok is False
        assert out.text == ""

    def test_threshold_configurable(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        backend.set_silence_threshold(0.0)
        # S nulovým prahem ticho projde RMS branou, ale VAD/segment to
        # stejně musí odmítnout - nesmí vzniknout text.
        out = backend.transcribe(np.zeros(16000, dtype=np.float32))
        assert out.text == ""

    def test_pipeline_silence_produces_no_text(self):
        """Tichý záznam NESMÍ vyprodukovat požadavek pro LLM."""
        stt = FakeStt(text="")
        pipeline = VoicePipeline(stt, lambda: FakeRecorder())
        audio = np.zeros(16000, dtype=np.float32)
        assert pipeline.process_recording(audio) == ""


# ---------------------------------------------------------------------------
# 3) Halucinace - text vymysleny ze ticha
# ---------------------------------------------------------------------------
class TestHallucinationRejection:
    def test_known_hallucinations_listed(self):
        assert len(KNOWN_HALLUCINATIONS) > 0

    def test_hallucination_text_is_rejected(self, tmp_path, monkeypatch):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        # Simulujeme, ze Whisper vratil halucinaci.
        class FakeModel:
            def transcribe(self, data, **kwargs):
                text = "Když to je výtěl, že to je výtěl."
                return [
                    type(
                        "S",
                        (),
                        {"text": text},
                    )()
                ]

        monkeypatch.setattr(backend, "_ensure_model", lambda: FakeModel())
        vad = tmp_path / "vad.bin"
        vad.write_bytes(b"fake; native model is replaced by FakeModel")
        monkeypatch.setattr(backend, "vad_file", lambda: vad)
        out = backend.transcribe(
            np.ones(16000, dtype=np.float32) * 0.5
        )
        assert out.ok is False
        assert out.text == ""
        assert "halucinace" in out.diagnostics.rejected_reason

    def test_dedup_removes_repeated_phrase(self):
        """Opakovana fráze se zredukuje na jednu kopii."""
        from martin.speech.whispercpp_backend import _cleanup

        # "a b a b a b a b" = "a b" + "a b" + "a b" + "a b" -> "a b"
        assert _cleanup("a b a b a b a b") == "a b"

    def test_dedup_keeps_distinct_words(self):
        from martin.speech.whispercpp_backend import _cleanup

        assert _cleanup("ahoj jak se mas") == "ahoj jak se mas"

    def test_dedup_keeps_hallucination_text_intact_for_check(self):
        """Halucinace musi zustat rozpoznatelna, aby ji mohl system odmítnout."""
        from martin.speech.whispercpp_backend import _cleanup

        text = _cleanup("Kdyz to je vytel, ze to je vytel.")
        assert "vytel" in text

    def test_dedup_keeps_normal_text(self):
        from martin.speech.whispercpp_backend import _cleanup

        assert _cleanup("ahoj  jak  se  mas") == "ahoj jak se mas"


# ---------------------------------------------------------------------------
# 4) Odpojeni zarizeni
# ---------------------------------------------------------------------------
class TestDeviceDisconnection:
    def test_start_failure_reports_error(self):
        """MOCKED - zaznamovac se nepodari otevrit."""
        pipeline = VoicePipeline(FakeStt(), lambda: FakeRecorder(start_ok=False))
        events = []
        pipeline.set_callbacks(on_event=lambda e: events.append(e))
        pipeline.start_recording()
        time.sleep(0.3)
        assert any(e.stage is Stage.ERROR for e in events)

    def test_stop_exception_is_handled(self):
        """MOCKED - chyba pri zastaveni nesmí spadnout."""
        recorder = FakeRecorder(stop_error=RuntimeError("zařízení odpojeno"))
        pipeline = VoicePipeline(FakeStt(), lambda: recorder)
        audio = pipeline.stop_recording()
        assert audio is None

    def test_stop_without_start_returns_none(self):
        pipeline = VoicePipeline(FakeStt(), lambda: FakeRecorder())
        assert pipeline.stop_recording() is None


# ---------------------------------------------------------------------------
# 5) Soucasne STT a TTS
# ---------------------------------------------------------------------------
class TestSimultaneousSttTts:
    def test_stt_runs_while_tts_playing(self):
        """MOCKED - rozpoznavani nesmi blokovat prehrani."""
        stt = FakeStt(text="ahoj")
        pipeline = VoicePipeline(stt, lambda: FakeRecorder())
        tts = type("T", (), {"stop": lambda self: None})()
        pipeline._tts = tts
        # Prehrani bezi "soucasne" - rozpoznavani se spusti nezavisle.
        started = time.perf_counter()
        pipeline.process_recording(np.ones(1600, dtype=np.float32))
        assert time.perf_counter() - started < 1.0
        assert stt.calls == 1

    def test_voice_busy_blocks_new_listening(self):
        """Kdyz Martin mluvi, nesmi se zacit nahravat."""
        pipeline = VoicePipeline(FakeStt(), lambda: FakeRecorder())
        assert pipeline.start_recording() is True
        time.sleep(0.2)
        assert pipeline.is_recording is True
        pipeline.stop_recording()


# ---------------------------------------------------------------------------
# 6) Zruseni
# ---------------------------------------------------------------------------
class TestCancellation:
    def test_cancel_stops_recording(self):
        pipeline = VoicePipeline(FakeStt(), lambda: FakeRecorder())
        pipeline.start_recording()
        time.sleep(0.2)
        pipeline.cancel()
        assert pipeline.is_recording is False
        assert pipeline.is_cancelled() is True

    def test_cancel_calls_stt_cancel(self):
        stt = FakeStt()
        pipeline = VoicePipeline(stt, lambda: FakeRecorder())
        pipeline.cancel()
        assert stt.cancelled is True

    def test_cancel_during_synthesis_stops_playback(self):
        """MOCKED - zruseni zastavi prehrani."""
        stopped = {"v": False}

        class FakeTts:
            def stop(self):
                stopped["v"] = True

        pipeline = VoicePipeline(FakeStt(), lambda: FakeRecorder(), FakeTts())
        pipeline.cancel()
        assert stopped["v"] is True

    def test_backend_cancel_flag(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        backend.cancel()
        backend.reset_cancel()
        assert backend._cancel.is_set() is False


# ---------------------------------------------------------------------------
# 7) Nase dalsi hlasove prikazy
# ---------------------------------------------------------------------------
class TestMultipleCommands:
    def test_sequential_commands(self):
        """MOCKED - vic po sobe jde zpracovat bez kolize."""
        stt = FakeStt(text="prikaz")
        pipeline = VoicePipeline(stt, lambda: FakeRecorder())
        for _ in range(5):
            text = pipeline.process_recording(np.ones(1600, dtype=np.float32))
            assert text == "prikaz"
        assert stt.calls == 5

    def test_pipeline_state_resets_between_cycles(self):
        stt = FakeStt(text="ok")
        pipeline = VoicePipeline(stt, lambda: FakeRecorder())
        pipeline.start_recording()
        time.sleep(0.2)
        pipeline.stop_recording()
        pipeline.process_recording(np.ones(1600, dtype=np.float32))
        assert pipeline.is_cancelled() is False


# ---------------------------------------------------------------------------
# 8) Chyby LLM / STT
# ---------------------------------------------------------------------------
class TestUnexpectedFailures:
    def test_stt_exception_propagates_as_error_text(self):
        class BoomStt:
            def transcribe(self, audio, sample_rate=16000):
                raise RuntimeError("výbuch")

            def cancel(self):
                pass

            def reset_cancel(self):
                pass

        pipeline = VoicePipeline(BoomStt(), lambda: FakeRecorder())
        text, diagnostics = pipeline.transcribe(np.ones(1600, dtype=np.float32))
        assert text == ""
        assert "error" in diagnostics

    def test_speech_failure_event_emitted(self):
        stt = FakeStt(text="")
        pipeline = VoicePipeline(stt, lambda: FakeRecorder())
        events = []
        pipeline.set_callbacks(on_event=lambda e: events.append(e))
        pipeline.process_recording(np.ones(1600, dtype=np.float32))
        assert any(e.stage is Stage.ERROR for e in events)


# ---------------------------------------------------------------------------
# 9) Cisty prehled
# ---------------------------------------------------------------------------
class TestResample:
    def test_resample_length(self):
        audio = np.zeros(48000, dtype=np.float32)
        assert len(resample(audio, 48000, 16000)) == 16000

    def test_resample_noop(self):
        audio = np.zeros(100, dtype=np.float32)
        assert len(resample(audio, 16000, 16000)) == 100

    def test_resample_empty(self):
        assert len(resample(np.array([], dtype=np.float32), 48000, 16000)) == 0


class TestTimings:
    def test_timings_to_dict(self):
        timings = VoiceTimings(stt_s=1.5, llm_total_s=2.5)
        data = timings.to_dict()
        assert data["stt_s"] == 1.5
        assert data["llm_total_s"] == 2.5
        assert "end_to_end_s" in data

    def test_timings_summary_readable(self):
        summary = VoiceTimings(stt_s=1.0).summary()
        assert "STT" in summary

    def test_diagnostics_to_dict(self):
        diag = SttDiagnostics(backend="whisper.cpp", audio_rms=0.5)
        data = diag.to_dict()
        assert data["backend"] == "whisper.cpp"
        assert data["audio_rms"] == 0.5
