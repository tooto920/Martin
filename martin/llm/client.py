"""Klient pro Ollama HTTP API s podporou streamingu a tool calling."""

from __future__ import annotations

import json
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
            for model in self.list_models():
                if model.get("name") == name:
                    return set(model.get("capabilities") or [])
        except OllamaError:
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
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        if images:
            payload["images"] = images

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise OllamaError(str(chunk["error"]))
                    yield chunk
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise OllamaError(f"Chyba spojení s Ollama: {exc}") from exc

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