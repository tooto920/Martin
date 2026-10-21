"""Nastavení aplikace - perzistentní, uložené jako JSON."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from martin.paths import (
    DEFAULT_CLOUD_MODEL,
    DEFAULT_LOCAL_MODEL,
    DEFAULT_OLLAMA_URL,
    SETTINGS_PATH,
)


@dataclass
class Settings:
    """Veškeré nastavení Martina na jednom místě."""

    # --- AI / LLM ---
    ollama_url: str = DEFAULT_OLLAMA_URL
    local_model: str = DEFAULT_LOCAL_MODEL
    cloud_model: str = DEFAULT_CLOUD_MODEL
    local_only: bool = False
    allow_cloud_fallback: bool = True
    auto_route: bool = True
    temperature: float = 0.6
    num_ctx: int = 8192
    max_tokens: int = 2048
    request_timeout: float = 120.0
    # Režim "přemýšlení" modelu. Vypnutý = rychlé odpovědi.
    thinking: bool = False

    # --- Hardware profily ---
    profile: str = "SMART"  # PERFORMANCE | GAMING | SMART
    keep_model_warm: bool = True
    gpu_layers: int = 99

    # --- Hlas / STT ---
    stt_model: str = "small"
    stt_compute_type: str = "int8"
    stt_device: str = "auto"
    stt_language: str = "cs"
    mic_device: str = ""
    wake_word_enabled: bool = False
    wake_word: str = "martine"
    push_to_talk: bool = True

    # --- TTS ---
    tts_enabled: bool = True
    tts_voice: str = "cs_CZ-jirka-medium"
    tts_rate: float = 1.0
    tts_output_device: str = ""
    speak_summaries: bool = True

    # --- Vzhled ---
    theme: str = "dark"  # dark | light
    floating_window: bool = True
    start_minimized: bool = False
    font_size: int = 10
    animations_enabled: bool = True

    # --- Chování ---
    language: str = "cs"
    speak_replies: bool = True
    log_security: bool = True

    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        extra = {k: v for k, v in (data or {}).items() if k not in known}
        obj = cls(**kwargs)
        if extra:
            obj.extra.update(extra)
        return obj


class SettingsStore:
    """Načítá a ukládá Settings atomicky."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path or SETTINGS_PATH)
        self._lock = threading.RLock()
        self._settings = Settings()
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def settings(self) -> Settings:
        with self._lock:
            return self._settings

    def load(self) -> Settings:
        """Načte nastavení z disku; při chybě vrátí výchozí hodnoty."""
        with self._lock:
            if self._path.is_file():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    self._settings = Settings.from_dict(raw)
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    self._settings = Settings()
            return self._settings

    def save(self) -> bool:
        """Uloží nastavení atomicky (dočasný soubor + přejmenování)."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(self._path.suffix + ".tmp")
                tmp.write_text(
                    json.dumps(self._settings.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(self._path)
                return True
            except OSError:
                return False

    def update(self, **changes: Any) -> Settings:
        """Aktualizuje hodnoty a uloží."""
        with self._lock:
            for key, value in changes.items():
                if hasattr(self._settings, key):
                    setattr(self._settings, key, value)
                else:
                    self._settings.extra[key] = value
            self.save()
            return self._settings

    def reset(self) -> Settings:
        with self._lock:
            self._settings = Settings()
            self.save()
            return self._settings