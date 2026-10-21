"""Cloud regressions: real HTTP cancellation, privacy modes, and budget accounting."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from martin.core.settings import Settings, SettingsStore
from martin.llm.client import ChatMessage, OllamaClient, OllamaError
from martin.llm.router import ModelRouter
from martin.llm.usage import UsageLedger


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_stop_closes_real_http_request_before_headers_or_during_body(phase):
    entered = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if phase == "body":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"message":{"content":"A"}}\n')
                self.wfile.flush()
            entered.set()
            release.wait(5)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = OllamaClient(f"http://127.0.0.1:{server.server_port}", timeout=15)
    errors = []
    metrics = []
    client.on_metrics = metrics.append

    def read():
        try:
            list(client.chat_stream("fake:cloud", [ChatMessage("user", "Ahoj")]))
        except OllamaError as e:
            errors.append(e)

    worker = threading.Thread(target=read)
    worker.start()
    try:
        assert entered.wait(3)
        start = time.perf_counter()
        client.cancel_active()
        worker.join(2)
        assert not worker.is_alive(), "Stop left a request blocked on the server"
        assert time.perf_counter() - start < 2
        assert errors[0].kind == "cancelled"
        assert metrics[0]["status"] == "cancelled"
        assert not client._operations
    finally:
        release.set()
        client.close()
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "code,kind",
    [
        (401, "auth"),
        (403, "auth"),
        (402, "credits"),
        (429, "rate_limit"),
        (404, "model"),
        (503, "server"),
    ],
)
def test_http_failure_is_visible_typed_and_never_replayed(code, kind):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(code, json={"error": "controlled failure"})

    client = OllamaClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OllamaError) as e:
            client.chat("test:cloud", [ChatMessage("user", "ahoj")])
        assert e.value.kind == kind
        assert len(calls) == 1
        if code == 429:
            with pytest.raises(OllamaError, match="nejdřív"):
                client.chat("test:cloud", [ChatMessage("user", "ahoj")])
            assert len(calls) == 1
    finally:
        client.close()


def test_total_deadline_even_when_server_does_not_close():
    async def handler(request):
        import asyncio

        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    client = OllamaClient(timeout=1, transport=httpx.MockTransport(handler))
    try:
        start = time.monotonic()
        with pytest.raises(OllamaError) as exc:
            client.chat("test:cloud", [ChatMessage("user", "ahoj")])
        assert exc.value.kind == "timeout"
        assert time.monotonic() - start < 2
    finally:
        client.close()


def test_modes_never_probe_or_load_local_models_for_cloud():
    class Client:
        def __getattr__(self, name):
            pytest.fail("routing queried server or local model: " + name)

    router = ModelRouter(Client())
    assert router.route("ahoj", "qwen3.5:4b", "nemotron-3-nano:30b-cloud").provider == "cloud"
    assert (
        router.route("obrazovka", "qwen3.5:4b", "nemotron-3-nano:30b-cloud").model
        == "nemotron-3-nano:30b-cloud"
    )
    with pytest.raises(ValueError):
        router.route("ahoj", "qwen3.5:4b", "qwen3.5:4b")
    with pytest.raises(ValueError):
        router.route("ahoj", "gemma4:cloud", "gemma4:cloud", local_only=True)


def test_legacy_migration_preserves_offline_choice_and_original_file(tmp_path):
    path = tmp_path / "settings.json"
    raw = '{"local_only":true,"stt_model":"small","custom":17}'
    path.write_text(raw)
    store = SettingsStore(path)
    assert store.settings.ai_mode == "Offline"
    assert store.settings.extra["custom"] == 17
    assert path.with_suffix(".pre-2.1.json").read_text() == raw
    assert path.read_text() == raw
    assert Settings.from_dict({"local_only": False}).ai_mode == "Cloud"


def test_usage_api_tokens_cost_cache_unknown_cancellation_and_budget(tmp_path):
    s = Settings()
    ledger = UsageLedger(tmp_path / "usage.db", s)
    payload = {
        "messages": [{"role": "user", "content": "private text not to store"}],
        "options": {"num_predict": 20},
    }
    ledger.begin("ok", "gemma4:cloud", payload)
    ledger.finish(
        {
            "request_id": "ok",
            "model": "gemma4:cloud",
            "status": "ok",
            "prompt_eval_count": 1000,
            "prompt_eval_cached_count": 500,
            "eval_count": 200,
            "elapsed_s": 1,
        }
    )
    snap = ledger.snapshot()
    assert snap["day"]["estimated_usd"] == pytest.approx(
        (500 * 0.14 + 500 * 0.05 + 200 * 0.4) / 1e6
    )
    ledger.begin("cancel", "gemma4:cloud", payload)
    ledger.finish(
        {"request_id": "cancel", "model": "gemma4:cloud", "status": "cancelled", "elapsed_s": 0.1}
    )
    assert ledger.snapshot()["day"]["unknown_cost_requests"] == 1
    assert b"private text" not in ledger.path.read_bytes()
    s.daily_request_limit = 2
    with pytest.raises(OllamaError, match="denní limit"):
        ledger.begin("third", "gemma4:cloud", payload)
    s.daily_request_limit = 0
    s.daily_budget_usd = 0.000001
    with pytest.raises(OllamaError, match="rozpočet"):
        ledger.begin("over", "gemma4:cloud", payload)


def test_empty_response_is_error_in_orchestrator(audit_log):
    from martin.llm.orchestrator import Orchestrator, OrchestratorEvent
    from martin.security.engine import PolicyEngine, ToolRegistry

    class Client:
        def chat_stream(self, *a, **kw):
            yield {"message": {"content": ""}, "done": True}

    client = Client()
    o = Orchestrator(client, PolicyEngine(ToolRegistry(), audit_log), ModelRouter(client))
    events = []
    o.run(
        [ChatMessage("user", "ahoj")],
        "local",
        "fake:cloud",
        emit=lambda e, d: events.append((e, d)),
    )
    assert any(e is OrchestratorEvent.ERROR and "prázdnou" in d["message"] for e, d in events)


def test_cancel_before_worker_start_does_not_reset_cancellation(audit_log):
    from martin.llm.orchestrator import Orchestrator
    from martin.security.engine import PolicyEngine, ToolRegistry

    class Client:
        def chat_stream(self, *a, **k):
            pytest.fail("request sent after Stop")

    client = Client()
    o = Orchestrator(client, PolicyEngine(ToolRegistry(), audit_log), ModelRouter(client))
    o.prepare()
    o.cancel()
    o.run([ChatMessage("user", "ahoj")], "local", "fake:cloud")


@pytest.fixture
def qt_context(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    import martin.app_context as module

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, "SettingsStore", lambda: SettingsStore(tmp_path / "settings.json"))
    for key, name in (
        ("DB_PATH", "memory.db"),
        ("CONVERSATIONS_DB_PATH", "conversations.db"),
        ("SECURITY_LOG_PATH", "security.jsonl"),
    ):
        monkeypatch.setattr(module, key, tmp_path / name)
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    ctx = module.AppContext()
    ctx.settings.speak_replies = False
    yield app, ctx
    ctx.shutdown()
    for _ in range(100):
        app.processEvents()
        time.sleep(0.002)
        if not ctx._chat_jobs:
            break
    assert not ctx._chat_jobs


def pump_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_qt_error_releases_busy_then_next_request_succeeds(qt_context):
    app, ctx = qt_context
    calls = []
    errors = []
    finished = []

    def serve(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(401, json={"error": "auth"})
        return httpx.Response(
            200,
            content=b'{"message":{"content":"OK"},"done":true,"eval_count":1,"prompt_eval_count":1}\n',
        )

    ctx.client._transport = httpx.MockTransport(serve)
    ctx.error_occurred.connect(errors.append)
    ctx.stream_finished.connect(finished.append)
    ctx.send_message("Ahoj")
    pump_until(app, lambda: len(finished) == 1)
    assert not ctx._busy.is_set()
    assert finished == ["Chyba připojení"] and errors
    ctx.send_message("Znovu")
    pump_until(app, lambda: len(finished) == 2)
    assert finished[-1] == "Připraven" and len(calls) == 2
    assert ctx.conversations.get_messages(ctx._conversation_id)[-1]["content"] == "OK"


def test_qt_stop_before_thread_start_sends_no_request(qt_context):
    app, ctx = qt_context
    calls = []
    finished = []
    ctx.client._transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    ctx.stream_finished.connect(finished.append)
    ctx.send_message("Ahoj")
    ctx.stop_generation()
    pump_until(app, lambda: bool(finished))
    assert not calls and finished == ["Zrušeno"]


def test_visible_stop_button_cancels_worker_and_restores_input(qt_context):
    from martin.ui.main_window import MainWindow
    import asyncio

    app, ctx = qt_context
    window = MainWindow(ctx)

    async def stalled(request):
        await asyncio.sleep(10)
        return httpx.Response(200, content=b'{"message":{"content":"late"},"done":true}\n')

    ctx.client._transport = httpx.MockTransport(stalled)
    finished = []
    ctx.stream_finished.connect(finished.append)
    try:
        ctx.send_message("Ahoj")
        pump_until(app, lambda: bool(ctx.client._operations))
        assert not window._chat._stop.isHidden()
        window._chat._stop.click()
        pump_until(app, lambda: bool(finished))
        assert finished == ["Zrušeno"]
        assert not ctx._busy.is_set()
        assert window._chat._stop.isHidden()
    finally:
        window._tray.hide()
        window._quitting = True
        window.close()
        window.deleteLater()


def test_chat_does_not_discard_input_while_context_is_busy(qt_context):
    from martin.ui.widgets.chat_view import ChatView

    app, ctx = qt_context
    view = ChatView(ctx)
    view._input.setPlainText("Moje další otázka")
    ctx._busy.set()
    view._submit()
    assert view._input.toPlainText() == "Moje další otázka"
    ctx._busy.clear()
    view.deleteLater()


def test_cloud_memory_setting_cannot_be_bypassed_by_model_tool_call(qt_context, monkeypatch):
    app, ctx = qt_context
    ctx.settings.cloud_memory_enabled = False

    def forbidden(*a, **kw):
        pytest.fail("disabled private memory was read by a model tool")

    monkeypatch.setattr(ctx.memory_manager, "search", forbidden)
    assert ctx.toolset._search_memory("private")["results"] == []


def test_direct_screenshot_denial_captures_nothing(qt_context, monkeypatch):
    app, ctx = qt_context
    finished = []
    confirmed = []

    def forbidden(*a, **kw):
        pytest.fail("image captured after denied permission")

    monkeypatch.setattr(ctx.vision, "analyze", forbidden)

    def reject(tool, args):
        confirmed.append(tool)
        ctx.respond_confirm(False)

    ctx.confirm_requested.connect(reject)
    ctx.stream_finished.connect(finished.append)
    ctx.request_screen_analysis()
    pump_until(app, lambda: bool(finished))
    assert confirmed == ["analyze_screen"]
    assert (
        "Snímek nebyl odeslán"
        in ctx.conversations.get_messages(ctx._conversation_id)[-1]["content"]
    )
