"""Odfiltrování citlivých údajů z logů a argumentů nástrojů.

Cílem je zaznamenat, co se stalo, ale nikdy neuložit hesla, tokeny
ani soukromé klíče do auditní stopy.
"""

from __future__ import annotations

import re
from typing import Any

# Klíče, u kterých hodnota je vždy považována za citlivou.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "cookie",
        "session_id",
        "private_key",
        "client_secret",
        "pin",
    }
)

# Maskovaná náhrada.
MASK = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Klíč hodnota ve formátu password=hodnota
    re.compile(
        r"(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key|auth(?:orization)?)"
        r"\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;}&]+)"
    ),
    # Bearer tokeny
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
    # Klíče ve formátu JSON
    re.compile(
        r"(?i)(\"(?:password|secret|token|api_key|apikey|authorization|credential)\"\s*:\s*)"
        r"(\"[^\"]*\"|[^,}\s]+)"
    ),
    # Připojení k databázi s heslem
    re.compile(r"(?i)\b([a-z]+://[^\s:/@]+):([^\s@]+)@"),
)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return MASK
    if isinstance(value, (int, float, bool)) or value is None:
        return MASK
    return MASK


def redact_secrets(data: Any, _depth: int = 0) -> Any:
    """Vrátí kopii dat s maskovanými citlivými hodnotami.

    Slovníky se prochází rekurzivně, řetězce se čistí pomocí vzorů.
    """
    if _depth > 12:
        return MASK
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                out[key] = _mask_value(value)
            else:
                out[key] = redact_secrets(value, _depth + 1)
        return out
    if isinstance(data, (list, tuple)):
        return [redact_secrets(item, _depth + 1) for item in data]
    if isinstance(data, str):
        return _redact_text(data)
    return data


def _redact_text(text: str) -> str:
    result = text
    result = _PATTERNS[0].sub(lambda m: f"{m.group(1)}={MASK}", result)
    result = _PATTERNS[1].sub("Bearer " + MASK, result)
    result = _PATTERNS[2].sub(lambda m: f"{m.group(1)}\"{MASK}\"", result)
    result = _PATTERNS[3].sub(lambda m: f"{m.group(1)}:{MASK}@", result)
    return result


def contains_secret(text: str) -> bool:
    """Zjišťuje, zda text obsahuje vzor citlivého údaje."""
    return _redact_text(text) != text