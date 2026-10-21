"""Policy engine - jediné místo, kde se rozhoduje, co smí být vykonáno.

Design:
  * Každý nástroj je registrován s pevnou bezpečnostní úrovní a vlastním
    validátorem argumentů. Úroveň nelze změnit z běhu (model to neumí).
  * Nástroje, které by vyžadovaly libovolný shell, jsou záměrně
    nepřítomné - neexistuje žádný "run_command" nástroj.
  * Validátor argumentů běží PŘED spuštěním akce a může akci odmítnout.
  * Model může pouze navrhnout akci; engine vždy rozhodne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from martin.security.audit import AuditLog
from martin.security.policy import PolicyDecision, PolicyOutcome, SecurityLevel

Validator = Callable[[dict[str, Any]], str | None]
Handler = Callable[..., Any]


@dataclass(slots=True)
class ToolSpec:
    """Specifikace jednoho nástroje."""

    name: str
    description: str
    level: SecurityLevel
    handler: Handler
    validator: Validator | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def ollama_schema(self) -> dict[str, Any]:
        """Schéma nástroje ve formátu, kterému rozumí Ollama."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
                or {"type": "object", "properties": {}, "required": []},
            },
        }


class ToolRegistry:
    """Registrace nástrojů dostupných modelu."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        level: SecurityLevel,
        handler: Handler,
        validator: Validator | None = None,
        parameters: dict[str, Any] | None = None,
        tags: Iterable[str] = (),
    ) -> ToolSpec:
        spec = ToolSpec(
            name=name,
            description=description,
            level=level,
            handler=handler,
            validator=validator,
            parameters=parameters or {},
            tags=tuple(tags),
        )
        self._tools[name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.ollama_schema() for spec in self._tools.values()]

    def by_tag(self, tag: str) -> list[ToolSpec]:
        return [spec for spec in self._tools.values() if tag in spec.tags]


class PolicyEngine:
    """Rozhoduje, zda je nástroj a jeho argumenty povoleny k vykonání."""

    def __init__(
        self,
        registry: ToolRegistry,
        audit: AuditLog,
        allow_cloud: bool = True,
        strict: bool = True,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._allow_cloud = allow_cloud
        self._strict = strict
        self._session_approvals: set[str] = set()

    @property
    def allow_cloud(self) -> bool:
        return self._allow_cloud

    def set_allow_cloud(self, value: bool) -> None:
        self._allow_cloud = value

    def approve(self, tool_name: str) -> None:
        """Udělí trvalé potvrzení pro konkrétní nástroj v této session."""
        self._session_approvals.add(tool_name)

    def revoke(self, tool_name: str) -> None:
        self._session_approvals.discard(tool_name)

    def evaluate(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        profile: str = "",
    ) -> PolicyDecision:
        """Posoudí nástroj a jeho argumenty. NEVYKONÁVÁ akci."""
        args = dict(args or {})
        spec = self._registry.get(tool_name)

        if spec is None:
            decision = PolicyDecision(
                outcome=PolicyOutcome.DENY,
                level=SecurityLevel.BLOCK,
                tool=tool_name,
                reason="Nástroj není registrován.",
                redacted_args={},
            )
            self._audit.record(
                tool_name, decision.outcome.value, decision.level.value,
                decision.reason, args, profile,
            )
            return decision

        # 1) Blokující úroveň - nikdy se nevykoná.
        if spec.level is SecurityLevel.BLOCK:
            decision = PolicyDecision(
                outcome=PolicyOutcome.DENY,
                level=SecurityLevel.BLOCK,
                tool=tool_name,
                reason=spec.description,
                redacted_args={},
            )
            self._audit.record(
                tool_name, decision.outcome.value, decision.level.value,
                decision.reason, args, profile,
            )
            return decision

        # 2) Validace argumentů aplikačním kódem.
        if spec.validator is not None:
            try:
                problem = spec.validator(args)
            except Exception as exc:  # noqa: BLE001 - validátor nesmí shodit běh
                problem = f"Validace argumentů selhala: {exc}"
            if problem:
                decision = PolicyDecision(
                    outcome=PolicyOutcome.DENY,
                    level=spec.level,
                    tool=tool_name,
                    reason=problem,
                    redacted_args={},
                )
                self._audit.record(
                    tool_name, decision.outcome.value, decision.level.value,
                    decision.reason, args, profile,
                )
                return decision

        # 3) Úroveň CONFIRM - vyžaduje schválení uživatelem.
        if spec.level is SecurityLevel.CONFIRM and tool_name not in self._session_approvals:
            decision = PolicyDecision(
                outcome=PolicyOutcome.CONFIRM_REQUIRED,
                level=spec.level,
                tool=tool_name,
                reason=spec.description,
                redacted_args={},
            )
            self._audit.record(
                tool_name, decision.outcome.value, decision.level.value,
                decision.reason, args, profile,
            )
            return decision

        decision = PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            level=spec.level,
            tool=tool_name,
            reason=spec.description,
            redacted_args={},
        )
        self._audit.record(
            tool_name, decision.outcome.value, decision.level.value,
            decision.reason, args, profile,
        )
        return decision

    def execute(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        profile: str = "",
    ) -> tuple[PolicyDecision, Any]:
        """Posoudí a následně vykoná nástroj.

        Vrací (decision, result). Pokud rozhodnutí není ALLOW, nástroj
        se nevykoná vůbec a result je None.
        """
        decision = self.evaluate(tool_name, args, profile)
        if not decision.allowed:
            return decision, None
        spec = self._registry.get(tool_name)
        assert spec is not None
        try:
            result = spec.handler(**(args or {}))
        except TypeError as exc:
            self._audit.record(
                tool_name, "error", spec.level.value,
                f"Neplatné argumenty: {exc}", args, profile,
            )
            return decision, {"error": f"Neplatné argumenty nástroje: {exc}"}
        except Exception as exc:  # noqa: BLE001 - nástroj nesmí shodit běh
            self._audit.record(
                tool_name, "error", spec.level.value,
                f"Chyba nástroje: {exc}", args, profile,
            )
            return decision, {"error": f"Nástroj selhal: {exc}"}
        return decision, result

    def describe(self) -> list[dict[str, Any]]:
        """Přehled nástrojů pro diagnostiku a UI."""
        return [
            {
                "name": spec.name,
                "level": spec.level.value,
                "description": spec.description,
                "tags": list(spec.tags),
            }
            for spec in self._registry.all()
        ]

    def has_tool(self, name: str) -> bool:
        return self._registry.get(name) is not None