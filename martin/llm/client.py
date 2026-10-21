"""Klient pro Ollama HTTP API s podporou streamingu a tool calling."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx


class OllamaError(RuntimeError):
    """Chyba při komunikaci s Ollama."""


@dataclass(slots=True)
class ChatMessage:
    """Jedna zpráva v konverzaci."""

    role: str  # system | user | assistant | tool
    content: str = ""
    images: list[str] = field(default_factory=list)  # base64 PNG
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_name: str = ""

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.images:
            payload["images"] = self.images
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        if self.tool_name:
            payload["name"] = self.tool_name
        return payload

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ChatMessage":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", "") or "",
            images=list(data.get("images") or []),
            tool_calls=list(data.get("tool_calls") or []),
            tool_name=data.get("name", "") or "",
        )


class OllamaClient:
    """Tenká, synchronní a streamovací klientská vrstva nad Ollama."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._responses: set[httpx.Response] = set()
        self._response_lock = threading.Lock()

    def cancel_active(self) -> None:
        with self._response_lock:
            responses = list(self._responses)
        for response in responses:
            try:
                response.close()
            except Exception:
                pass

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 - zavření nesmí shodit běh
            pass

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- základní API ---------------------------------------------------
    def list_models(self) -> list[dict[str, Any]]:
        """Vrací seznam dostupných modelů."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags", timeout=10.0)
            response.raise_for_status()
            return list(response.json().get("models", []))
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise OllamaError(f"Nelze získat seznam modelů: {exc}") from exc

    def model_names(self) -> list[str]:
        try:
            return [m.get("name", "") for m in self.list_models()]
        except OllamaError:
            return []

    def is_available(self) -> bool:
        """Kontrola, zda Ollama běží a odpovídá."""
        try:
            self.list_models()
            return True
        except OllamaError:
            return False

    def model_capabilities(self, name: str) -> set[str]:
        """Vrací schopnosti modelu (vision, tools, ...)."""
        try:
            response = self._client.post(f"{self.base_url}/api/show", json={"model": name}, timeout=10)
            response.raise_for_status()
            capabilities = response.json().get("capabilities")
            if capabilities is not None:
                return set(capabilities)
            for model in self.list_models():
                if model.get("name") == name:
                    return set(model.get("capabilities") or [])
        except (OllamaError, httpx.HTTPError, ValueError):
            pass
        return set()

    def has_vision(self, name: str) -> bool:
        return "vision" in self.model_capabilities(name)

    def has_tools(self, name: str) -> bool:
        return "tools" in self.model_capabilities(name)

    def is_cloud(self, name: str) -> bool:
        """Rozpozná cloudový model (suffix :cloud nebo remote_model)."""
        if name.endswith(":cloud") or "-cloud" in name:
            return True
        try:
            for model in self.list_models():
                if model.get("name") == name and model.get("remote_model"):
                    return True
        except OllamaError:
            pass
        return False

    # --- chat ----------------------------------------------------------
    def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        images: list[str] | None = None,
        think: bool | None = False,
        keep_alive: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Streamuje odpověď z Ollama po jednotlivých chunkách.

        `think=False` vypne režim "přemýšlení" modelu. Pro rychlého
        asistenta je to zásadní - s rozmyšlením trvá odpověď na
        krátký dotaz desítky sekund místo méně než sekundy.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_api() for m in messages],
            "stream": True,
        }
        if think is not None:
            payload["think"] = think
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        if images:
            for message in reversed(payload["messages"]):
                if message["role"] == "user":
                    message["images"] = images
                    break

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                with self._response_lock:
                    self._responses.add(response)
                completed = False
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaError("Ollama vrátila neplatný stream.") from exc
                    if not isinstance(chunk, dict):
                        raise OllamaError("Ollama vrátila neplatný stream.")
                    if chunk.get("error"):
                        raise OllamaError(str(chunk["error"]))
                    yield chunk
                    if chunk.get("done"):
                        completed = True
                        break
                if not completed:
                    raise OllamaError("Odpověď Ollama byla předčasně přerušena.")
        except httpx.HTTPError as exc:
            raise OllamaError(f"Chyba spojení s Ollama: {exc}") from exc
        finally:
            if "response" in locals():
                with self._response_lock:
                    self._responses.discard(response)

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool | None = False,
    ) -> dict[str, Any]:
        """Synchronní dotaz, vrací celou odpověď."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_api() for m in messages],
            "stream": False,
        }
        if think is not None:
            payload["think"] = think
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        try:
            response = self._client.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Chyba spojení s Ollama: {exc}") from exc

    def generate(self, model: str, prompt: str, system: str = "") -> str:
        """Jednoduchá generace bez nástrojů (např. shrnutí)."""
        messages = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=prompt))
        data = self.chat(model, messages)
        return (data.get("message") or {}).get("content", "")
