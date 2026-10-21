"""Definice bezpečnostních úrovní a výsledku rozhodnutí."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SecurityLevel(str, Enum):
    """Úroveň oprávnění požadovaná nástrojem.

    SAFE    - bezpečné read-only akce a spuštění schválených aplikací.
    CONFIRM - změna uživatelských dat, vyžaduje výslovné potvrzení.
    BLOCK   - destruktivní operace, eskalace práv, obejití zabezpečení.
    """

    SAFE = "safe"
    CONFIRM = "confirm"
    BLOCK = "block"

    @property
    def rank(self) -> int:
        return {"safe": 0, "confirm": 1, "block": 2}[self.value]


class PolicyOutcome(str, Enum):
    """Výsledek posouzení nástroje."""

    ALLOW = "allow"
    CONFIRM_REQUIRED = "confirm_required"
    DENY = "deny"


@dataclass(slots=True)
class PolicyDecision:
    """Rozhodnutí politika k vykonání nástroje."""

    outcome: PolicyOutcome
    level: SecurityLevel
    tool: str
    reason: str = ""
    redacted_args: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome is PolicyOutcome.ALLOW

    @property
    def needs_confirmation(self) -> bool:
        return self.outcome is PolicyOutcome.CONFIRM_REQUIRED

    @property
    def denied(self) -> bool:
        return self.outcome is PolicyOutcome.DENY

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "level": self.level.value,
            "tool": self.tool,
            "reason": self.reason,
            "args": self.redacted_args,
        }