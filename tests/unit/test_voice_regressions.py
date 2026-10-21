"""Regresni testy: GUI zustava responsivni, zrušeni a uklizeni workeru.

Testy s `MOCKED` označenim používají falešné objekty místo skutečného
zvuku. Testy nad skutečným hardwarem jsou v tests/integration.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from martin.speech.pipeline import Stage, VoicePipeline
from martin.speech.streaming_tts import StreamingTTS
from martin.speech.whispercpp_backend import WhisperCppBackend


class DummyRecorder:
    """MOCKED nahravac."""

    def __init__(self, audio=None):
        self._audio = audio
        self.stopped = False

    def start(self):
        return True

    def stop(self):
        self.stopped = True
        return self._audio

    @property
    def sample_rate(self):
        return 16000


class SlowStt:
    """MOCKED rozpoznavani se zpožděním."""

    def __init__(self, delay=0.5):
        self.delay = delay
        self.cancelled = False
        self.calls = 0

    def transcribe(self, audio, sample_rate=16000):
        self.calls += 1
        deadline = time.time() + self.delay
        while time.time() < deadline and not self.cancelled:
            time.sleep(0.01)
        return type(
            "O", (), {"text": "vysledek", "error": "", "to_dict": lambda s: {}}
        )()

    def cancel(self):
        self.cancelled = True

    def reset_cancel(self):
        self.cancelled = False


class TestGuiResponsiveness:
    """GUI vlákno nesmí čekat na I/O."""

    def test_start_recording_returns_immediately(self):
        """Otevreni mikrofonu musi bezet asynchronne."""
        pipeline = VoicePipeline(SlowStt(), lambda: DummyRecorder())
        t0 = time.perf_counter()
        pipeline.start_recording()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1, f"start_recording blokoval {elapsed * 1000:.0f} ms"

    def test_process_recording_runs_in_caller_thread(self):
        """Rozpoznavani bezi tam, kde je zavolano - UI si to ridi samo."""
        stt = SlowStt(delay=0.3)
        pipeline = VoicePipeline(stt, lambda: DummyRecorder())
        t0 = time.perf_counter()
        pipeline.process_recording(np.ones(1600, dtype=np.float32))
        elapsed = time.perf_counter() - t0
        assert elapsed >= 0.25

    def test_timings_recorded(self):
        stt = SlowStt(delay=0.2)
        pipeline = VoicePipeline(stt, lambda: DummyRecorder())
        pipeline.transcribe(np.ones(1600, dtype=np.float32))
        timings = pipeline.timings
        assert timings.stt_s > 0


class TestWorkerCleanup:
    def test_stop_recording_releases_recorder(self):
        recorder = DummyRecorder()
        pipeline = VoicePipeline(SlowStt(), lambda: recorder)
        pipeline.start_recording()
        time.sleep(0.2)
        pipeline.stop_recording()
        assert recorder.stopped is True
        assert pipeline.is_recording is False

    def test_cancel_stops_everything(self):
        stt = SlowStt()
        stopped = {"v": False}

        class FakeTts:
            def stop(self):
                stopped["v"] = True

        pipeline = VoicePipeline(stt, lambda: DummyRecorder(), FakeTts())
        pipeline.start_recording()
        time.sleep(0.15)
        pipeline.cancel()
        assert pipeline.is_cancelled() is True
        assert pipeline.is_recording is False
        assert stt.cancelled is True
        assert stopped["v"] is True

    def test_no_thread_leak_after_cancel(self):
        before = threading.active_count()
        for _ in range(5):
            pipeline = VoicePipeline(SlowStt(delay=0.05), lambda: DummyRecorder())
            pipeline.start_recording()
            time.sleep(0.05)
            pipeline.cancel()
        time.sleep(0.4)
        after = threading.active_count()
        assert after - before <= 3, f"uniklo vlakno: {before} -> {after}"


class TestStreamingTtsCancellation:
    def test_stop_clears_queue(self):
        class FakeTts:
            def __init__(self):
                self.stopped = False
                self._output_device = ""

            def synthesize(self, text):
                return type("R", (), {"ok": True, "audio_path": "", "error": ""})()

            def stop(self):
                self.stopped = True

        tts = FakeTts()
        streamer = StreamingTTS(tts)
        streamer.push_text("Toto je první věta, která má dost délky.")
        streamer.stop()
        assert tts.stopped is True

    def test_push_after_stop_is_ignored(self):
        class FakeTts:
            def __init__(self):
                self.calls = 0
                self._output_device = ""

            def synthesize(self, text):
                self.calls += 1
                return type("R", (), {"ok": True, "audio_path": "", "error": ""})()

            def stop(self):
                pass

        tts = FakeTts()
        streamer = StreamingTTS(tts)
        streamer.stop()
        streamer.push_text("Toto je věta po zastavení, která by se neměla syntézovat.")
        assert tts.calls == 0


class TestBackendResilience:
    def test_status_never_raises(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        status = backend.status()
        assert status["backend"] == "whisper.cpp"
        assert isinstance(status["available"], bool)

    def test_set_model_resets_loaded_model(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        backend._model = object()
        backend.set_model("base")
        assert backend._model is None
        assert backend.model_size == "base"

    def test_set_same_model_keeps_loaded(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        backend._model = object()
        backend.set_model("small")
        assert backend._model is not None

    def test_unload_releases_model(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        backend._model = object()
        backend.unload()
        assert backend._model is None

    def test_transcribe_with_nan_audio(self, tmp_path):
        """NaN nesmí shodit rozpoznavani."""
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        audio = np.full(1600, np.nan, dtype=np.float32)
        out = backend.transcribe(audio)
        assert out.ok is False

    def test_transcribe_with_extreme_values(self, tmp_path):
        backend = WhisperCppBackend(model_size="small", models_dir=tmp_path)
        audio = np.full(1600, 10.0, dtype=np.float32)
        out = backend.transcribe(audio)
        assert isinstance(out.ok, bool)


class TestPipelineEvents:
    def test_all_stages_emitted(self):
        class OkStt:
            def transcribe(self, audio, sample_rate=16000):
                return type(
                    "O", (), {"text": "ahoj", "error": "", "to_dict": lambda s: {}}
                )()

            def cancel(self):
                pass

            def reset_cancel(self):
                pass

        pipeline = VoicePipeline(OkStt(), lambda: DummyRecorder())
        stages = []
        pipeline.set_callbacks(on_event=lambda e: stages.append(e.stage))
        pipeline.process_recording(np.ones(1600, dtype=np.float32))
        assert Stage.TRANSCRIBING in stages
        assert Stage.ERROR not in stages

    def test_error_stage_on_empty_result(self):
        class EmptyStt:
            def transcribe(self, audio, sample_rate=16000):
                return type(
                    "O", (), {"text": "", "error": "nic", "to_dict": lambda s: {}}
                )()

            def cancel(self):
                pass

            def reset_cancel(self):
                pass

        pipeline = VoicePipeline(EmptyStt(), lambda: DummyRecorder())
        stages = []
        pipeline.set_callbacks(on_event=lambda e: stages.append(e.stage))
        result = pipeline.process_recording(np.ones(1600, dtype=np.float32))
        assert result == ""
        assert Stage.ERROR in stages