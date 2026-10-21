"""Auditní stopa bezpečnostních rozhodnutí.

Zapisuje se jako JSON Lines do souboru. Každý záznam obsahuje čas,
nástroj, rozhodnutí a maskované argumenty. Hesla a tokeny se nikdy
nezapisují - před uložením procházejí přes redactor.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from martin.security.redaction import redact_secrets


@dataclass(slots=True)
class AuditEvent:
    """Jeden záznam v bezpečnostní stopě."""

    tool: str
    outcome: str
    level: str
    reason: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.timestamp,
            "tool": self.tool,
            "outcome": self.outcome,
            "level": self.level,
            "reason": self.reason,
            "args": self.args,
            "profile": self.profile,
        }


class AuditLog:
    """Thread-safe zapisovač bezpečnostních událostí do JSONL souboru."""

    def __init__(self, path: Path, max_entries: int = 5000) -> None:
        self._path = Path(path)
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._events: list[AuditEvent] = []

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        tool: str,
        outcome: str,
        level: str,
        reason: str = "",
        args: dict[str, Any] | None = None,
        profile: str = "",
    ) -> AuditEvent:
        """Zaznamená událost a uloží ji na disk."""
        event = AuditEvent(
            tool=tool,
            outcome=outcome,
            level=level,
            reason=reason,
            args=redact_secrets(args or {}),
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            profile=profile,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_entries:
                del self._events[: len(self._events) - self._max_entries]
        self._flush(event)
        return event

    def _flush(self, event: AuditEvent) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            # Audit nesmí shodit celou aplikaci; chyba se loguje do stderr.
            import sys

            print(f"[martin.audit] zápis auditní stopy selhal: {event.tool}", file=sys.stderr)

    def events(self) -> list[AuditEvent]:
        """Vrací kopii událostí v paměti."""
        with self._lock:
            return list(self._events)

    def load(self) -> list[dict[str, Any]]:
        """Načte události z disku (pokud soubor existuje)."""
        if not self._path.is_file():
            return []
        out: list[dict[str, Any]] = []
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return out
        return out