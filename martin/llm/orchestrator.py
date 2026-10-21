"""Orchestrátor - agentní smyčka, která spojuje LLM, nástroje a bezpečnost.

Směrovaný chat běží ve vlákně (QThread), aby grafické rozhraní nikdy
neblokovalo. UI dostává události přes signály.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from martin.core.logging import get_logger
from martin.llm.client import ChatMessage, OllamaClient, OllamaError
from martin.llm.router import ModelRouter, RoutingDecision
from martin.security.engine import PolicyEngine

log = get_logger("martin.orchestrator")

MAX_TOOL_ROUNDS = 6


class OrchestratorEvent(str, Enum):
    """Události vysílané do UI."""

    STATE = "state"
    TEXT = "text"
    ROUTE = "route"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONFIRM_REQUEST = "confirm_request"
    ERROR = "error"
    DONE = "done"


@dataclass(slots=True)
class ToolCallRequest:
    """Žádost o potvrzení akce."""

    tool: str
    args: dict[str, Any]
    reason: str
    call_id: str = ""

    def describe(self) -> str:
        return f"{self.tool}: {json.dumps(self.args, ensure_ascii=False)}"


class Orchestrator:
    """Agentní smyčka s tool callingem a bezpečnostní kontrolou."""

    def __init__(
        self,
        client: OllamaClient,
        policy: PolicyEngine,
        router: ModelRouter,
        system_prompt: str = "",
    ) -> None:
        self._client = client
        self._policy = policy
        self._router = router
        self._system_prompt = system_prompt
        self._lock = threading.RLock()
        self._pending_confirm: ToolCallRequest | None = None
        self._confirm_event = threading.Event()
        self._confirm_result = False

    # -- veřejné API ----------------------------------------------------
    def set_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt

    def confirm(self, approved: bool) -> None:
        """Odpověď uživatele na žádost o potvrzení."""
        with self._lock:
            self._confirm_result = approved
            self._pending_confirm = None
        self._confirm_event.set()

    def run(
        self,
        messages: list[ChatMessage],
        local_model: str,
        cloud_model: str,
        local_only: bool = False,
        allow_cloud: bool = True,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
        emit: Callable[[OrchestratorEvent, dict[str, Any]], None] | None = None,
        images: list[str] | None = None,
        profile: str = "",
        think: bool | None = False,
    ) -> list[ChatMessage]:
        """Spustí konverzační kolo. Vrací rozšířený seznam zpráv."""
        emit = emit or (lambda _e, _d: None)
        with self._lock:
            conversation = list(messages)
            if self._system_prompt:
                conversation.insert(0, ChatMessage(role="system", content=self._system_prompt))

        routing = self._route(
            conversation, local_model, cloud_model, local_only, allow_cloud, emit
        )
        if routing is None:
            return conversation

        active_tools = tools if routing.requires_tools or tools else None
        for round_index in range(MAX_TOOL_ROUNDS):
            try:
                assistant = self._stream_once(
                    routing, conversation, active_tools, options, images, emit, think
                )
            except OllamaError as exc:
                emit(OrchestratorEvent.ERROR, {"message": str(exc)})
                return conversation

            conversation.append(assistant)
            if not assistant.tool_calls:
                emit(OrchestratorEvent.DONE, {"message": assistant.content})
                return conversation

            for call in assistant.tool_calls:
                result = self._run_tool(call, conversation, profile, emit)
                if result is None:
                    # Uživatel akci odmítl nebo ji zrušil.
                    emit(
                        OrchestratorEvent.TEXT,
                        {"text": "\n\n_Akce byla zrušena uživatelem._\n"},
                    )
                    emit(OrchestratorEvent.DONE, {"message": ""})
                    return conversation
                conversation.append(result)

        emit(
            OrchestratorEvent.ERROR,
            {"message": "Překročen limit počtu kroků s nástroji."},
        )
        return conversation

    # -- interní --------------------------------------------------------
    def _route(
        self,
        conversation: list[ChatMessage],
        local_model: str,
        cloud_model: str,
        local_only: bool,
        allow_cloud: bool,
        emit: Callable[[OrchestratorEvent, dict[str, Any]], None],
    ) -> RoutingDecision | None:
        last_user = next(
            (m for m in reversed(conversation) if m.role == "user"), None
        )
        text = last_user.content if last_user else ""
        try:
            decision = self._router.route(
                text, local_model, cloud_model, local_only, allow_cloud
            )
        except ValueError as exc:
            emit(OrchestratorEvent.ERROR, {"message": str(exc)})
            return None
        emit(
            OrchestratorEvent.ROUTE,
            {
                "model": decision.model,
                "provider": decision.provider,
                "reason": decision.reason,
            },
        )
        return decision

    def _stream_once(
        self,
        routing: RoutingDecision,
        conversation: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        options: dict[str, Any] | None,
        images: list[str] | None,
        emit: Callable[[OrchestratorEvent, dict[str, Any]], None],
        think: bool | None = False,
    ) -> ChatMessage:
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for chunk in self._client.chat_stream(
            routing.model,
            conversation,
            tools=tools,
            options=options,
            images=images,
            think=think,
        ):
            message = chunk.get("message") or {}
            piece = message.get("content") or ""
            if piece:
                content_parts.append(piece)
                emit(OrchestratorEvent.TEXT, {"text": piece})
            for call in message.get("tool_calls") or []:
                tool_calls.append(call)
        return ChatMessage(
            role="assistant",
            content="".join(content_parts),
            tool_calls=tool_calls,
        )

    def _run_tool(
        self,
        call: dict[str, Any],
        conversation: list[ChatMessage],
        profile: str,
        emit: Callable[[OrchestratorEvent, dict[str, Any]], None],
    ) -> ChatMessage | None:
        function = call.get("function") or {}
        name = function.get("name", "")
        raw_args = function.get("arguments") or {}
        args = self._parse_args(raw_args)
        call_id = str(call.get("id") or name)

        emit(OrchestratorEvent.TOOL_CALL, {"tool": name, "args": args})

        decision = self._policy.evaluate(name, args, profile)
        if decision.denied:
            emit(
                OrchestratorEvent.TEXT,
                {"text": f"\n\n⛔ _Akce `{name}` byla zablokována bezpečnostní politikou._\n"},
            )
            return ChatMessage(
                role="tool",
                content=json.dumps(
                    {"error": "Akce zablokována bezpečnostní politikou", "reason": decision.reason},
                    ensure_ascii=False,
                ),
                tool_name=name,
            )

        if decision.needs_confirmation:
            request = ToolCallRequest(
                tool=name, args=args, reason=decision.reason, call_id=call_id
            )
            emit(
                OrchestratorEvent.CONFIRM_REQUEST,
                {"tool": name, "args": args, "reason": decision.reason},
            )
            approved = self._ask_user(request)
            if not approved:
                emit(OrchestratorEvent.TOOL_RESULT, {"tool": name, "result": "zamítnuto"})
                return None
            self._policy.approve(name)

        _decision, result = self._policy.execute(name, args, profile)
        emit(OrchestratorEvent.TOOL_RESULT, {"tool": name, "result": result})
        return ChatMessage(
            role="tool",
            content=json.dumps(result, ensure_ascii=False, default=str),
            tool_name=name,
        )

    def _ask_user(self, request: ToolCallRequest) -> bool:
        self._confirm_event.clear()
        with self._lock:
            self._pending_confirm = request
            self._confirm_result = False
        self._confirm_event.wait(timeout=120.0)
        with self._lock:
            return self._confirm_result

    @staticmethod
    def _parse_args(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {}
        return {}