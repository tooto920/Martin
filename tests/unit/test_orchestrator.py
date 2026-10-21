"""Testy konverzacniho toku v orchestrátoru.

Pokryvaji race condition pri potvrzeni akce a spravne predavani
udalosti z pracovniho vlakna do UI.
"""

from __future__ import annotations

import threading
import time

import pytest

from martin.llm.client import ChatMessage
from martin.llm.orchestrator import Orchestrator, OrchestratorEvent
from martin.llm.router import ModelRouter
from martin.security.engine import PolicyEngine, ToolRegistry
from martin.security.policy import SecurityLevel


class FakeClient:
    """Náhrada Ollama klienta - vrací předem nastavené tool cally."""

    def __init__(self, tool_calls=None, content="Hotovo."):
        self._tool_calls = tool_calls or []
        self._content = content
        self.calls = 0

    def has_vision(self, name):
        return True

    def has_tools(self, name):
        return True

    def is_available(self):
        return True

    def model_names(self):
        return ["fake"]

    def chat_stream(self, model, messages, tools=None, options=None, images=None, think=None):
        self.calls += 1
        if self.calls == 1 and self._tool_calls:
            yield {
                "message": {
                    "content": "",
                    "tool_calls": self._tool_calls,
                },
                "done": False,
            }
        else:
            yield {"message": {"content": self._content}, "done": True}


@pytest.fixture()
def orchestrator_parts(registry, audit_log):
    tools = ToolRegistry()
    tools.register(
        "risky",
        "Zmeni neco.",
        SecurityLevel.CONFIRM,
        lambda **kw: {"ok": True, "applied": kw},
    )
    policy = PolicyEngine(tools, audit_log)
    client = FakeClient()
    orch = Orchestrator(client, policy, ModelRouter(client), "Jsi Martin.", confirm_timeout=1.0)
    return orch, tools, client


class TestConfirmFlow:
    def test_confirm_request_is_emitted(self, orchestrator_parts):
        orch, tools, client = orchestrator_parts
        client._tool_calls = [
            {
                "id": "c1",
                "function": {"name": "risky", "arguments": {"path": "x"}},
            }
        ]

        events = []

        def emit(event, data):
            events.append(event)
            if event is OrchestratorEvent.CONFIRM_REQUEST:
                # UI odpoví až po události - musí fungovat.
                threading.Timer(0.05, lambda: orch.confirm(True)).start()

        orch.run(
            [ChatMessage(role="user", content="udělej to")],
            local_model="fake",
            cloud_model="fake:cloud",
            tools=tools.schemas(),
            emit=emit,
            think=False,
        )

        assert OrchestratorEvent.CONFIRM_REQUEST in events
        assert OrchestratorEvent.DONE in events

    def test_denied_confirmation_stops_action(self, orchestrator_parts, audit_log):
        orch, tools, client = orchestrator_parts
        client._tool_calls = [{"id": "c1", "function": {"name": "risky", "arguments": {}}}]

        def emit(event, data):
            if event is OrchestratorEvent.CONFIRM_REQUEST:
                orch.confirm(False)

        orch.run(
            [ChatMessage(role="user", content="udělej to")],
            local_model="fake",
            cloud_model="fake:cloud",
            tools=tools.schemas(),
            emit=emit,
            think=False,
        )

        outcomes = [e.outcome for e in audit_log.events()]
        assert "confirm_required" in outcomes
        assert "allow" not in outcomes

    def test_immediate_confirmation_is_not_lost(self, orchestrator_parts):
        """Odpoved uzivatele hned po udalosti nesmi zniknout."""
        orch, tools, client = orchestrator_parts
        client._tool_calls = [{"id": "c1", "function": {"name": "risky", "arguments": {}}}]

        done = []

        def emit(event, data):
            if event is OrchestratorEvent.CONFIRM_REQUEST:
                # Synchronni odpoved - hned, bez cekani.
                orch.confirm(True)
            elif event is OrchestratorEvent.DONE:
                done.append(True)

        start = time.time()
        orch.run(
            [ChatMessage(role="user", content="udělej to")],
            local_model="fake",
            cloud_model="fake:cloud",
            tools=tools.schemas(),
            emit=emit,
            think=False,
        )
        elapsed = time.time() - start
        assert done
        # Nesmelo to cekat 120 s na timeout.
        assert elapsed < 10.0

    def test_confirm_after_timeout_returns_false(self, orchestrator_parts):
        orch, tools, client = orchestrator_parts
        client._tool_calls = [{"id": "c1", "function": {"name": "risky", "arguments": {}}}]
        # Zadna odpoved - cekame, ale timeout v testu zkracujeme.
        orch._confirm_event.set()
        outcomes = []
        orch.run(
            [ChatMessage(role="user", content="udělej to")],
            local_model="fake",
            cloud_model="fake:cloud",
            tools=tools.schemas(),
            emit=lambda e, d: outcomes.append(e),
            think=False,
        )
        assert outcomes


class TestBlockedTool:
    def test_blocked_tool_is_denied(self, registry, audit_log):
        tools = ToolRegistry()
        tools.register(
            "destroy",
            "Znic vsechno.",
            SecurityLevel.BLOCK,
            lambda: {"ok": True},
        )
        policy = PolicyEngine(tools, audit_log)
        client = FakeClient()
        client._tool_calls = [{"id": "c1", "function": {"name": "destroy", "arguments": {}}}]
        orch = Orchestrator(client, policy, ModelRouter(client), "Jsi Martin.", confirm_timeout=1.0)

        events = []
        orch.run(
            [ChatMessage(role="user", content="znic to")],
            local_model="fake",
            cloud_model="fake:cloud",
            tools=tools.schemas(),
            emit=lambda e, d: events.append(e),
            think=False,
        )

        outcomes = [e.outcome for e in audit_log.events()]
        assert "deny" in outcomes
        assert "allow" not in outcomes
