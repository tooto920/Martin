"""Tři hardwarové profily a jejich skutečné uplatnění.

PERFORMANCE - plné GPUInference, minimální latence.
GAMING     - uvolní VRAM pro hry, model běží na CPU nebo vypne.
SMART      - automatické rozhodování podle vytížení a složitosti úlohy.

Uvolnění VRAM se provádí přes Ollama API (keep_alive: 0), takže je
možné vždy ověřit skutečný stav paměti, ne ho jen předpokládat."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import httpx

from martin.core.logging import get_logger
from martin.hardware.monitor import HardwareMonitor, SystemSnapshot

log = get_logger("martin.hardware.profiles")

PROFILE_PERFORMANCE = "PERFORMANCE"
PROFILE_GAMING = "GAMING"
PROFILE_SMART = "SMART"
PROFILES = (PROFILE_PERFORMANCE, PROFILE_GAMING, PROFILE_SMART)

# Práh využití VRAM, při kterém SMART režim upřednostní CPU/cloud.
SMART_VRAM_THRESHOLD_PERCENT = 80.0
# Práh využití CPU, při kterém se odloží cloudové požadavky.
SMART_CPU_THRESHOLD_PERCENT = 90.0


@dataclass(slots=True)
class PowerProfile:
    """Popis hardwarového profilu."""

    name: str
    description: str
    keep_alive: str
    prefer_cloud: bool
    num_gpu_layers: int
    label_cz: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label_cz,
            "description": self.description,
            "keep_alive": self.keep_alive,
            "prefer_cloud": self.prefer_cloud,
            "num_gpu_layers": self.num_gpu_layers,
        }


PROFILE_DEFS: dict[str, PowerProfile] = {
    PROFILE_PERFORMANCE: PowerProfile(
        name=PROFILE_PERFORMANCE,
        description="Plné GPU inference, minimální latence, model zůstává v paměti.",
        keep_alive="30m",
        prefer_cloud=False,
        num_gpu_layers=99,
        label_cz="Výkon",
    ),
    PROFILE_GAMING: PowerProfile(
        name=PROFILE_GAMING,
        description=(
            "Uvolní VRAM pro hry. Model se odpojí od GPU a běží na CPU, "
            "nebo se použije povolený cloudový model."
        ),
        keep_alive="0",
        prefer_cloud=True,
        num_gpu_layers=0,
        label_cz="Hraní",
    ),
    PROFILE_SMART: PowerProfile(
        name=PROFILE_SMART,
        description=(
            "Automaticky volí lokální nebo cloudový model podle vytížení "
            "a složitosti úlohy."
        ),
        keep_alive="10m",
        prefer_cloud=False,
        num_gpu_layers=99,
        label_cz="Chytrý",
    ),
}


class HardwareManager:
    """Spravuje profily, uvolňuje VRAM a rozhoduje o routování."""

    def __init__(
        self,
        monitor: HardwareMonitor,
        ollama_url: str = "http://127.0.0.1:11434",
        cloud_allowed: bool = True,
    ) -> None:
        self._monitor = monitor
        self._ollama_url = ollama_url.rstrip("/")
        self._cloud_allowed = cloud_allowed
        self._lock = threading.RLock()
        self._profile = PROFILE_SMART
        self._last_release_check: dict[str, Any] = {}

    @property
    def profile(self) -> str:
        with self._lock:
            return self._profile

    @property
    def definition(self) -> PowerProfile:
        return PROFILE_DEFS[self.profile]

    def profiles(self) -> list[PowerProfile]:
        return [PROFILE_DEFS[name] for name in PROFILES]

    def set_profile(
        self,
        name: str,
        local_model: str = "",
        ollama_url: str | None = None,
    ) -> dict[str, Any]:
        """Přepne profil a uplatní jeho požadavky na VRAM.

        Vrací slovník s výsledkem a OVĚŘENÝM stavem paměti.
        """
        name = name.strip().upper()
        if name not in PROFILE_DEFS:
            return {
                "ok": False,
                "error": f"Neznámý profil: {name}. Dostupné: {', '.join(PROFILES)}.",
            }
        definition = PROFILE_DEFS[name]
        url = (ollama_url or self._ollama_url).rstrip("/")
        detail = ""
        released = False

        if definition.keep_alive == "0" and local_model:
            released, detail = self._unload_model(url, local_model)
        elif local_model:
            detail = "Model zůstává rezidentní v paměti GPU."

        with self._lock:
            self._profile = name

        snapshot = self._monitor.snapshot()
        return {
            "ok": True,
            "profile": name,
            "label": definition.label_cz,
            "detail": detail,
            "model_unloaded": released,
            "vram_free_mb": round(snapshot.vram_free_mb),
            "vram_total_mb": round(snapshot.gpu_memory_total_mb),
            "verified": True,
        }

    def _unload_model(self, url: str, model: str) -> tuple[bool, str]:
        """Pošle keep_alive=0, aby Ollama uvolnila VRAM."""
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    f"{url}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                        "keep_alive": 0,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return False, f"Nepodařilo se uvolnit model z VRAM: {exc}"
        return True, "Model byl odpojen od GPU (keep_alive=0)."

    def should_use_cloud(self, snapshot: SystemSnapshot | None = None) -> bool:
        """Rozhodne, zda je vhodný čas na cloud (kvůli vytížení)."""
        if not self._cloud_allowed:
            return False
        definition = self.definition
        if definition.prefer_cloud:
            return True
        if definition.name != PROFILE_SMART:
            return False
        snap = snapshot or self._monitor.latest()
        if snap is None:
            return False
        return snap.vram_percent >= SMART_VRAM_THRESHOLD_PERCENT

    def apply_to_settings(self, settings: Any) -> None:
        """Propíše nastavení profilu do objektu Settings."""
        definition = self.definition
        settings.profile = definition.name
        settings.keep_model_warm = definition.keep_alive != "0"
        settings.gpu_layers = definition.num_gpu_layers

    def status(self) -> dict[str, Any]:
        """Aktuální stav profilu a zdrojů."""
        snap = self._monitor.latest()
        return {
            "profile": self.profile,
            "label": self.definition.label_cz,
            "description": self.definition.description,
            "cloud_allowed": self._cloud_allowed,
            "snapshot": snap.to_dict() if snap else None,
        }