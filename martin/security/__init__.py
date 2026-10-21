"""Bezpečnostní vrstva Martina.

Zásadní pravidlo: bezpečnost je vynucena kódem aplikace, nikoli modelem.
Model navrhuje akci, ale rozhodnutí o povolení vždy přijímá PolicyEngine
na základě deklarované úrovně nástroje, allowlistu a validace argumentů.
"""

from martin.security.policy import SecurityLevel, PolicyDecision, PolicyOutcome
from martin.security.audit import AuditLog, AuditEvent
from martin.security.engine import PolicyEngine, ToolRegistry, ToolSpec
from martin.security.redaction import redact_secrets, contains_secret

__all__ = [
    "SecurityLevel",
    "PolicyDecision",
    "PolicyOutcome",
    "AuditLog",
    "AuditEvent",
    "PolicyEngine",
    "ToolRegistry",
    "ToolSpec",
    "redact_secrets",
    "contains_secret",
]