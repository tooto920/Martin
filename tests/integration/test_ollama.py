"""Integrační testy proti běžícímu Ollama.

Tyto testy se přeskočí, pokud Ollama není dostupná.
"""

from __future__ import annotations

import pytest

from martin.llm.client import ChatMessage, OllamaClient, OllamaError

pytestmark = pytest.mark.integration

LOCAL_MODEL = "qwen3.5:4b"


@pytest.fixture(scope="module")
def client():
    c = OllamaClient(timeout=120.0)
    if not c.is_available():
        pytest.skip("Ollama není dostupná")
    return c


@pytest.fixture(scope="module")
def model_name(client):
    names = client.model_names()
    if LOCAL_MODEL in names:
        return LOCAL_MODEL
    pytest.skip(f"Model {LOCAL_MODEL} není nainstalován")


class TestOllamaClient:
    def test_is_available(self, client):
        assert client.is_available() is True

    def test_list_models_returns_names(self, client):
        names = client.model_names()
        assert isinstance(names, list)
        assert len(names) > 0

    def test_local_model_has_vision(self, client, model_name):
        assert client.has_vision(model_name) is True

    def test_local_model_has_tools(self, client, model_name):
        assert client.has_tools(model_name) is True

    def test_chat_returns_content(self, client, model_name):
        response = client.chat(
            model_name,
            [ChatMessage(role="user", content="Napiš jedno slovo: test")],
        )
        content = (response.get("message") or {}).get("content", "")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_stream_yields_chunks(self, client, model_name):
        chunks = []
        for chunk in client.chat_stream(
            model_name,
            [ChatMessage(role="user", content="Řekni: dobrý den")],
        ):
            piece = (chunk.get("message") or {}).get("content", "")
            if piece:
                chunks.append(piece)
        assert len(chunks) > 0
        assert "".join(chunks).strip() != ""

    def test_tool_calling_produces_call(self, client, model_name):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "Testovací nástroj.",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                },
            }
        ]
        calls = []
        for chunk in client.chat_stream(
            model_name,
            [
                ChatMessage(
                    role="user",
                    content="Použij nástroj test_tool s hodnotou name='Martin'.",
                )
            ],
            tools=tools,
        ):
            calls.extend((chunk.get("message") or {}).get("tool_calls") or [])
        assert len(calls) > 0
        assert calls[0]["function"]["name"] == "test_tool"

    def test_invalid_model_raises(self, client):
        with pytest.raises(OllamaError):
            client.chat(
                "model-ktere-neexistuje-12345",
                [ChatMessage(role="user", content="ahoj")],
            )