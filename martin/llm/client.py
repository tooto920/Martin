"""Klient pro Ollama HTTP API s podporou streamingu a tool calling."""

from __future__ import annotations

import json
import threading
import asyncio
import queue
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx


class OllamaError(RuntimeError):
    """Chyba při komunikaci s Ollama."""

    def __init__(self, message, *, kind="connection", status_code=None):
        super().__init__(message)
        self.kind, self.status_code = kind, status_code


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
        transport=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._responses: set[httpx.Response] = set()
        self._response_lock = threading.Lock()
        self._operations = {}
        self._transport = transport
        self.before_request = None
        self.on_metrics = None
        self._cancelled = threading.Event()
        self._retry_after = 0.0
        self._rate_failures = 0

    def prepare_request(self):
        self._cancelled.clear()

    def cancel_active(self) -> None:
        self._cancelled.set()
        with self._response_lock:
            operations = list(self._operations.values())
        for loop, task in operations:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        with self._response_lock:
            responses = list(self._responses)
        for response in responses:
            try:
                response.close()
            except Exception:
                pass

    def close(self) -> None:
        self.cancel_active()
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
            response = self._client.post(
                f"{self.base_url}/api/show", json={"model": name}, timeout=10
            )
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

        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        metrics = {"request_id": request_id, "model": model, "status": "error"}
        if self._cancelled.is_set():
            raise OllamaError("Požadavek zrušen.", kind="cancelled")
        if time.monotonic() < self._retry_after:
            raise OllamaError(
                f"Ollama omezuje požadavky. Další pokus nejdřív za {max(1, int(self._retry_after - time.monotonic()))} s.",
                kind="rate_limit",
            )
        if self.before_request:
            self.before_request(request_id, model, payload)
        inbox = queue.SimpleQueue()

        async def fetch():
            loop, task = asyncio.get_running_loop(), asyncio.current_task()
            with self._response_lock:
                self._operations[request_id] = (loop, task)
            try:
                if self._cancelled.is_set():
                    raise asyncio.CancelledError()
                async with asyncio.timeout(max(1, self.timeout)):
                    async with httpx.AsyncClient(
                        transport=self._transport, timeout=httpx.Timeout(self.timeout, connect=10)
                    ) as client:
                        async with client.stream(
                            "POST", f"{self.base_url}/api/chat", json=payload
                        ) as response:
                            metrics["headers_s"] = time.perf_counter() - started
                            if response.status_code >= 400:
                                await response.aread()
                                if response.status_code == 429:
                                    self._rate_failures += 1
                                    try:
                                        delay = float(response.headers.get("retry-after", 0))
                                    except ValueError:
                                        delay = 0
                                    self._retry_after = time.monotonic() + min(
                                        60, max(delay, 2 ** min(self._rate_failures, 6))
                                    )
                                raise self._response_error(response)
                            completed = False
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    chunk = json.loads(line)
                                except ValueError as exc:
                                    raise OllamaError(
                                        "Ollama vrátila neplatný stream.", kind="protocol"
                                    ) from exc
                                if not isinstance(chunk, dict):
                                    raise OllamaError(
                                        "Ollama vrátila neplatný stream.", kind="protocol"
                                    )
                                if chunk.get("error"):
                                    raise OllamaError(str(chunk["error"])[:400], kind="provider")
                                if (chunk.get("message") or {}).get(
                                    "content"
                                ) and "ttft_s" not in metrics:
                                    metrics["ttft_s"] = time.perf_counter() - started
                                inbox.put(chunk)
                                if chunk.get("done"):
                                    completed = True
                                    for key in (
                                        "prompt_eval_count",
                                        "eval_count",
                                        "prompt_eval_cached_count",
                                        "total_duration",
                                        "load_duration",
                                    ):
                                        if key in chunk:
                                            metrics[key] = chunk[key]
                                    metrics["status"] = "ok"
                                    self._rate_failures = 0
                                    break
                            if not completed:
                                raise OllamaError(
                                    "Odpověď Ollama byla předčasně přerušena.", kind="protocol"
                                )
            except asyncio.CancelledError:
                metrics["status"] = "cancelled"
                inbox.put(OllamaError("Požadavek zrušen.", kind="cancelled"))
            except (TimeoutError, httpx.TimeoutException):
                metrics["status"] = "timeout"
                inbox.put(
                    OllamaError(
                        "Vypršel časový limit odpovědi. Zkus požadavek znovu.", kind="timeout"
                    )
                )
            except Exception as exc:
                metrics["error_kind"] = getattr(exc, "kind", "connection")
                inbox.put(
                    exc
                    if isinstance(exc, OllamaError)
                    else OllamaError("Nelze se spojit s Ollama. Zkontroluj server a připojení.")
                )
            finally:
                metrics["elapsed_s"] = time.perf_counter() - started
                with self._response_lock:
                    self._operations.pop(request_id, None)
                if self.on_metrics:
                    try:
                        self.on_metrics(dict(metrics))
                    except Exception:
                        pass
                inbox.put(None)

        runner = threading.Thread(
            target=lambda: asyncio.run(fetch()), name=f"martin-http-{request_id}", daemon=True
        )
        runner.start()
        try:
            while True:
                item = inbox.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            with self._response_lock:
                operation = self._operations.get(request_id)
            if operation:
                loop, task = operation
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass
            runner.join(timeout=3)

    @staticmethod
    def _response_error(response):
        code = response.status_code
        kind = {401: "auth", 403: "auth", 402: "credits", 429: "rate_limit", 404: "model"}.get(
            code, "server"
        )
        try:
            message = str(response.json().get("error", "")).lower()
        except (ValueError, AttributeError):
            message = ""
        if code in (402, 403, 429) and any(
            word in message for word in ("credit", "balance", "usage limit", "quota exceeded")
        ):
            kind = "credits"
        messages = {
            "auth": "Ollama Cloud vyžaduje přihlášení. Přihlas se v oficiální aplikaci Ollama.",
            "credits": "Ollama hlásí nedostatečný kredit. Zkontroluj účet na ollama.com/settings/usage.",
            "rate_limit": "Ollama omezila počet požadavků. Počkej a použij Zkusit znovu.",
            "model": "Zvolený model není dostupný. Zkontroluj jeho přesný název v nastavení.",
        }
        return OllamaError(
            messages.get(kind, f"Ollama vrátila chybu HTTP {code}."), kind=kind, status_code=code
        )

    def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool | None = False,
    ) -> dict[str, Any]:
        """Synchronní dotaz, vrací celou odpověď."""
        content, calls, final = [], [], {}
        for chunk in self.chat_stream(model, messages, tools=tools, options=options, think=think):
            message = chunk.get("message") or {}
            content.append(message.get("content") or "")
            calls.extend(message.get("tool_calls") or [])
            final = chunk
        return {
            **final,
            "message": {"role": "assistant", "content": "".join(content), "tool_calls": calls},
        }

    def generate(self, model: str, prompt: str, system: str = "") -> str:
        """Jednoduchá generace bez nástrojů (např. shrnutí)."""
        messages = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=prompt))
        data = self.chat(model, messages)
        return (data.get("message") or {}).get("content", "")
