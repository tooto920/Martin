"""Regressions of real application paths; fake devices control race timing."""
import threading
import time

import numpy as np
import pytest

from martin.speech.pipeline import VoicePipeline
from martin.speech.whispercpp_backend import WhisperCppBackend


def test_cancel_while_microphone_opens_releases_late_device():
    opened = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class Recorder:
        def start(self):
            opened.set()
            release.wait(2)
            return True

        def stop(self):
            closed.set()
            return np.zeros(100, dtype=np.float32)

    p = VoicePipeline(WhisperCppBackend(), Recorder)
    p.start_recording()
    assert opened.wait(1)
    p.cancel()
    release.set()
    assert closed.wait(1), "cancel leaked the device opened after cancellation"
    assert not p.is_recording


def test_capture_at_native_rate_is_normalized_before_stt():
    class Recorder:
        sample_rate = 48000

        def start(self):
            return True

        def stop(self):
            return np.ones(4800, dtype=np.float32)

    p = VoicePipeline(WhisperCppBackend(), Recorder)
    p.start_recording()
    time.sleep(0.02)
    audio = p.stop_recording()
    assert audio is not None and len(audio) == 1600
    assert p.timings.record_duration_s == pytest.approx(0.1)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_chat_reply_gets_its_own_bubble(qapp):
    from PySide6.QtCore import QObject, Signal
    from martin.core.settings import Settings
    from martin.ui.widgets.chat_view import ChatView

    class Context(QObject):
        stream_started = Signal()
        stream_chunk = Signal(str)
        stream_finished = Signal(str)
        error_occurred = Signal(str)
        listening_changed = Signal(bool)
        speaking_changed = Signal(bool)
        settings = Settings()

    ctx = Context()
    view = ChatView(ctx)
    view.add_message("user", "Ahoj")
    ctx.stream_started.emit()
    ctx.stream_chunk.emit("Ahoj, jak můžu pomoct?")
    assert view._messages.count() == 2
    assert view._messages.itemAt(0).widget()._body.text() == "Ahoj"
    assert view._messages.itemAt(1).widget()._role == "assistant"
    view.deleteLater()


def test_stt_nonfinite_audio_never_enters_native_decoder(monkeypatch):
    backend = WhisperCppBackend(silence_rms=0)
    def forbidden():
        pytest.fail("invalid PCM reached native model initialization")
    monkeypatch.setattr(backend, "_ensure_model", forbidden)
    result = backend.transcribe(np.full(16000, np.nan, dtype=np.float32))
    assert not result.ok


def test_streaming_tts_finishes_without_dropping_sentences(monkeypatch):
    from martin.speech.streaming_tts import StreamingTTS
    calls = []
    class TTS:
        def synthesize(self, text):
            calls.append(text)
            return type("Result", (), {"ok": False, "error": "", "audio_path": ""})()
        def stop(self):
            pass
    stream = StreamingTTS(TTS(), max_queue=2)
    for _ in range(9):
        stream.push_text("**Tohle je dostatečně dlouhá věta.** ")
    stream.finish()
    assert stream.wait(2), "playback consumer never finished after the end of input"
    assert len(calls) == 9
    assert all("*" not in text for text in calls)
    assert stream.dropped_sentences == 0
    assert stream._thread is not None and not stream._thread.is_alive()


def test_token_boundaries_preserve_whitespace_and_links():
    from martin.speech.streaming_tts import StreamingTTS
    calls = []
    class TTS:
        def synthesize(self, text):
            calls.append(text)
            return type("Result", (), {"ok": False, "error": "", "audio_path": ""})()
        def stop(self):
            pass
    stream = StreamingTTS(TTS())
    for token in ["Přečti", " ", "[ten", "to odkaz]", "(https://example.com)", " a ", "**tento text**."]:
        stream.push_text(token)
    stream.finish()
    assert stream.wait(2)
    assert calls == ["Přečti tento odkaz a tento text."]


def test_callback_does_not_need_lifecycle_lock(monkeypatch):
    """A driver waiting for its callback must not wait for stop's lock."""
    import sys
    from martin.speech.stt import AudioRecorder
    callbacks = []
    class Stream:
        def __init__(self, **kwargs):
            callbacks.append(kwargs["callback"])
        def start(self):
            pass
        def stop(self):
            thread = threading.Thread(target=lambda: callbacks[0](np.zeros((10, 1)), 10, None, None), daemon=True)
            thread.start()
            thread.join(0.5)
            assert not thread.is_alive(), "stop and callback deadlocked"
        def close(self):
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", type("SD", (), {"InputStream": Stream})())
    recorder = AudioRecorder()
    assert recorder.start()
    recorder.stop()


def test_every_sensitive_call_requires_confirmation(audit_log):
    from martin.llm.orchestrator import Orchestrator, OrchestratorEvent
    from martin.security.engine import PolicyEngine, ToolRegistry
    from martin.security.policy import SecurityLevel
    registry = ToolRegistry()
    applied = []
    registry.register("change", "Změna", SecurityLevel.CONFIRM,
                      lambda value: applied.append(value))
    policy = PolicyEngine(registry, audit_log)
    orchestrator = Orchestrator(None, policy, None)
    requests = []
    def emit(event, data):
        if event is OrchestratorEvent.CONFIRM_REQUEST:
            requests.append(data["args"])
            orchestrator.confirm(len(requests) == 1)
    for value in (10, 90):
        orchestrator._run_tool({"function": {"name": "change", "arguments": {"value": value}}}, [], "", emit)
    assert requests == [{"value": 10}, {"value": 90}]
    assert applied == [10]
    assert policy.evaluate("change", {"value": 10}).needs_confirmation


def test_open_app_validator_and_resolved_target_are_checked(monkeypatch, audit_log, tmp_path):
    from martin.tools.tools import ToolSet
    from martin.system.apps import AppEntry
    from martin.security.engine import PolicyEngine, ToolRegistry
    called = []
    class Apps:
        def find(self, name):
            return AppEntry(name, str(tmp_path), kind="folder")
        def resolve_target(self, entry):
            return tmp_path / "powershell.exe"
    registry = ToolSet(ToolRegistry(), Apps(), volume=object()).register_all()
    policy = PolicyEngine(registry, audit_log)
    monkeypatch.setattr("martin.tools.tools.subprocess.Popen", lambda *a, **k: called.append(a))
    decision, result = policy.execute("open_app", {"name": "Test"})
    assert decision.allowed, decision.reason
    assert not result["ok"] and not called


def test_folder_alias_uses_same_validated_target(monkeypatch, audit_log, tmp_path):
    from martin.tools.tools import ToolSet
    from martin.security.engine import PolicyEngine, ToolRegistry
    folder = tmp_path / "Downloads"
    folder.mkdir()
    opened = []
    monkeypatch.setattr("martin.tools.tools.ALLOWED_FOLDER_ROOTS", (folder,))
    monkeypatch.setattr("martin.tools.tools.os.startfile", opened.append)
    registry = ToolSet(ToolRegistry(), object(), volume=object()).register_all()
    decision, result = PolicyEngine(registry, audit_log).execute("open_folder", {"path": "Downloads"})
    assert decision.allowed and result["ok"]
    assert opened == [str(folder.resolve())]


def test_truncated_ollama_stream_is_an_error():
    import httpx
    from martin.llm.client import ChatMessage, OllamaClient, OllamaError
    client = OllamaClient()
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'{"message":{"content":"partial"}}\n')))
    try:
        with pytest.raises(OllamaError, match="přerušena"):
            list(client.chat_stream("test", [ChatMessage("user", "Ahoj")]))
    finally:
        client.close()


def test_vram_unload_is_not_verified_when_model_is_still_loaded(monkeypatch):
    import httpx
    from martin.hardware.profiles import HardwareManager
    responses = []
    real_client = httpx.Client
    def handle(request):
        responses.append(request.url.path)
        return httpx.Response(200, json={"models": [{"name": "test:latest"}]})
    monkeypatch.setattr("martin.hardware.profiles.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(handle)))
    released, detail = HardwareManager(None)._unload_model("http://localhost:11434", "test:latest")
    assert not released and "stále načtený" in detail
    assert responses == ["/api/chat", "/api/ps"]


def test_missing_espeak_data_is_rejected_before_native_exit(tmp_path):
    from martin.speech.tts import PiperTTS
    with pytest.raises(RuntimeError, match="Chybí data Piper/eSpeak"):
        PiperTTS._validate_phonemizer_data(tmp_path)


def test_model_cannot_capture_screen_without_user_confirmation(audit_log):
    from martin.tools.tools import ToolSet
    from martin.security.engine import PolicyEngine, ToolRegistry
    registry = ToolSet(ToolRegistry(), object(), volume=object()).register_all()
    decision, result = PolicyEngine(registry, audit_log).execute("analyze_screen", {"question": "Popiš obrazovku"})
    assert decision.needs_confirmation
    assert result is None
