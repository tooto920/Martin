"""Nástroje dostupné modelu - jediná cesta, jak model ovlivní systém.

Zásady:
  * Žádný nástroj nespouští libovolný příkaz z řetězce.
  * Každý nástroj má pevnou úroveň oprávnění a vlastní validátor.
  * Nástroje pracují s registry aplikací a systémem, ne s volnou cestou.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from martin.core.logging import get_logger
from martin.security.engine import ToolRegistry
from martin.security.policy import SecurityLevel
from martin.system.apps import AppRegistry, BLOCKED_EXECUTABLES
from martin.system.stats import collect_stats
from martin.system.windows import VolumeController, WindowManager

log = get_logger("martin.tools")

# Adresáře, do kterých smí Martin otevřít složku.
ALLOWED_FOLDER_ROOTS = (
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
)

WINDOWS_SETTINGS_PAGES = {
    "system": "ms-settings:",
    "display": "ms-settings:display",
    "bluetooth": "ms-settings:bluetooth",
    "network": "ms-settings:network",
    "wifi": "ms-settings:network-wifi",
    "sound": "ms-settings:sound",
    "notifications": "ms-settings:notifications",
    "power": "ms-settings:powersleep",
    "storage": "ms-settings:storagesense",
    "apps": "ms-settings:appsfeatures",
    "privacy": "ms-settings:privacy",
    "update": "ms-settings:windowsupdate",
    "startup": "ms-settings:startupapps",
    "defaultapps": "ms-settings:defaultapps",
    "language": "ms-settings:regionlanguage",
    "time": "ms-settings:dateandtime",
    "about": "ms-settings:about",
    "taskbar": "ms-settings:taskbar",
    "mouse": "ms-settings:mousetouchpad",
    "keyboard": "ms-settings:keyboard",
    "printers": "ms-settings:printers",
}


def _folder_target(path_text: str) -> Path:
    target = Path(os.path.expandvars(path_text)).expanduser()
    if not target.is_absolute():
        for root in ALLOWED_FOLDER_ROOTS:
            if target == Path(root.name):
                return root.resolve()
    return target.resolve()


def _valid_folder(path_text: str) -> str | None:
    """Ověří, že složka je existující a povolená."""
    if not path_text or not path_text.strip():
        return "Složka není zadána."
    try:
        target = _folder_target(path_text)
    except (OSError, RuntimeError) as exc:
        return f"Neplatná cesta: {exc}"
    if not target.exists():
        return f"Složka neexistuje: {target}"
    if not target.is_dir():
        return f"Cesta není složka: {target}"
    try:
        resolved_roots = [root.resolve() for root in ALLOWED_FOLDER_ROOTS if root.exists()]
    except OSError:
        resolved_roots = []
    for root in resolved_roots:
        try:
            target.relative_to(root)
            return None
        except ValueError:
            continue
    return (
        "Složka mimo povolené oblasti. Povoleno je otevřít pouze složky "
        "na ploše, v Dokumentech, Stažených souborech, Obrázcích, Videa a Hudbě."
    )


def _valid_app_name(name: str) -> str | None:
    if not name or not name.strip():
        return "Název aplikace není zadán."
    if len(name) > 120:
        return "Název aplikace je příliš dlouhý."
    return None


class ToolSet:
    """Sestaví sadu nástrojů pro model."""

    def __init__(
        self,
        registry: ToolRegistry,
        apps: AppRegistry,
        volume: VolumeController | None = None,
        memory: Any | None = None,
        vision: Any | None = None,
        hardware: Any | None = None,
    ) -> None:
        self._registry = registry
        self._apps = apps
        self._volume = volume or VolumeController()
        self._memory = memory
        self._vision = vision
        self._hardware = hardware

    def register_all(self) -> ToolRegistry:
        """Zaregistruje všechny nástroje. Vrací registry."""
        r = self._registry

        # --- spouštění aplikací (SAFE) ---
        r.register(
            "open_app",
            "Spustí nainstalovanou aplikaci nebo hru podle názvu.",
            SecurityLevel.SAFE,
            self._open_app,
            validator=lambda args: _valid_app_name(str(args.get("name", ""))),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Název aplikace, např. 'Microsoft Flight Simulator 2024'.",
                    }
                },
                "required": ["name"],
            },
            tags=("windows",),
        )

        r.register(
            "list_apps",
            "Vypíše dostupné aplikace a hry, které lze spustit.",
            SecurityLevel.SAFE,
            self._list_apps,
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Volitelný filtr."}},
                "required": [],
            },
            tags=("windows",),
        )

        r.register(
            "open_folder",
            "Otevře složku v Průzkumníku souborů.",
            SecurityLevel.SAFE,
            self._open_folder,
            validator=lambda args: _valid_folder(str(args.get("path", ""))),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Cesta ke složce, např. 'Downloads' nebo plná cesta.",
                    }
                },
                "required": ["path"],
            },
            tags=("windows",),
        )

        r.register(
            "focus_window",
            "Přinese do popředí existující okno aplikace.",
            SecurityLevel.SAFE,
            self._focus_window,
            validator=lambda args: _valid_app_name(str(args.get("title", ""))),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Část názvu okna."}
                },
                "required": ["title"],
            },
            tags=("windows",),
        )

        r.register(
            "list_windows",
            "Vypíše otevřená okna aplikací.",
            SecurityLevel.SAFE,
            self._list_windows,
            parameters={"type": "object", "properties": {}, "required": []},
            tags=("windows",),
        )

        r.register(
            "open_browser",
            "Otevře webovou stránku v defaultním prohlížeči.",
            SecurityLevel.SAFE,
            self._open_browser,
            validator=self._validate_url,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL adresa (http/https)."}
                },
                "required": ["url"],
            },
            tags=("windows", "web"),
        )

        r.register(
            "open_windows_settings",
            "Otevře stránku v Nastavení Windows.",
            SecurityLevel.SAFE,
            self._open_settings,
            validator=self._validate_settings_page,
            parameters={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "string",
                        "description": "Stránka nastavení, např. 'display', 'sound', 'bluetooth'.",
                    }
                },
                "required": ["page"],
            },
            tags=("windows",),
        )

        # --- systémové informace (SAFE) ---
        r.register(
            "system_stats",
            "Vrátí aktuální stav CPU, RAM, disku, baterie a GPU.",
            SecurityLevel.SAFE,
            self._system_stats,
            parameters={"type": "object", "properties": {}, "required": []},
            tags=("system",),
        )

        r.register(
            "list_audio_devices",
            "Vypíše dostupná zvuková zařízení (mikrofon, reproduktory).",
            SecurityLevel.SAFE,
            self._list_audio_devices,
            parameters={"type": "object", "properties": {}, "required": []},
            tags=("system", "audio"),
        )

        # --- změny systému (CONFIRM) ---
        r.register(
            "set_volume",
            "Nastaví hlasitost systému na zadanou hodnotu v procentech.",
            SecurityLevel.CONFIRM,
            self._set_volume,
            validator=self._validate_volume,
            parameters={
                "type": "object",
                "properties": {
                    "percent": {"type": "integer", "description": "Hlasitost 0-100."}
                },
                "required": ["percent"],
            },
            tags=("system", "audio"),
        )

        r.register(
            "adjust_volume",
            "Zvýší nebo sníží hlasitost o zadaný počet procent.",
            SecurityLevel.CONFIRM,
            self._adjust_volume,
            validator=self._validate_volume,
            parameters={
                "type": "object",
                "properties": {
                    "delta": {
                        "type": "integer",
                        "description": "Změna hlasitosti, např. 10 nebo -10.",
                    }
                },
                "required": ["delta"],
            },
            tags=("system", "audio"),
        )

        # --- paměť (SAFE / CONFIRM) ---
        r.register(
            "search_memory",
            "Vyhledá v dlouhodobé paměti uložené informace.",
            SecurityLevel.SAFE,
            self._search_memory,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Hledaný výraz."}
                },
                "required": ["query"],
            },
            tags=("memory",),
        )

        r.register(
            "remember",
            "Uloží důležitou informaci do dlouhodobé paměti.",
            SecurityLevel.CONFIRM,
            self._remember,
            validator=self._validate_memory_text,
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Co si má Martin pamatovat."},
                    "category": {
                        "type": "string",
                        "description": "Kategorie: preference, aplikace, projekt, osobni, jine.",
                    },
                },
                "required": ["content"],
            },
            tags=("memory",),
        )

        # --- hardware profily (CONFIRM) ---
        r.register(
            "set_power_profile",
            "Přepne hardwarový profil Martina (PERFORMANCE, GAMING, SMART).",
            SecurityLevel.CONFIRM,
            self._set_profile,
            validator=self._validate_profile,
            parameters={
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "PERFORMANCE, GAMING nebo SMART.",
                    }
                },
                "required": ["profile"],
            },
            tags=("hardware",),
        )

        # --- obrazovka (SAFE) ---
        r.register(
            "analyze_screen",
            "Vyfotí obrazovku a nechá model ji analyzovat.",
            SecurityLevel.SAFE,
            self._analyze_screen,
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Co chceš na obrazovce zjistit.",
                    }
                },
                "required": ["question"],
            },
            tags=("vision",),
        )

        return r

    # --- implementace nástrojů ----------------------------------------
    def _open_app(self, name: str) -> dict[str, Any]:
        entry = self._apps.find(name)
        if entry is None:
            return {
                "ok": False,
                "error": f"Aplikace '{name}' nebyla nalezena.",
                "hint": "Použij nástroj list_apps pro seznam dostupných aplikací.",
            }
        if entry.is_blocked:
            return {
                "ok": False,
                "error": f"Spuštění '{entry.name}' je z bezpečnostních důvodů zakázáno.",
            }
        try:
            if entry.kind == "steam":
                os.startfile(entry.target)  # registered steam://rungameid URI
            elif entry.kind == "url":
                os.startfile(entry.target)  # noqa: S606 - cíl je z registru/start menu
            else:
                target = self._apps.resolve_target(entry)
                if target is None:
                    return {
                        "ok": False,
                        "error": f"Soubor aplikace nebyl nalezen: {entry.target}",
                    }
                if target.name.lower() in BLOCKED_EXECUTABLES or target.suffix.lower() != ".exe":
                    return {"ok": False, "error": "Cíl aplikace není povolený spustitelný soubor."}
                subprocess.Popen([str(target)], close_fds=True)
        except OSError as exc:
            return {"ok": False, "error": f"Spuštění selhalo: {exc}"}
        return {"ok": True, "app": entry.name, "target": entry.target, "kind": entry.kind}

    def _list_apps(self, query: str = "") -> dict[str, Any]:
        matches = self._apps.search(query, limit=40)
        return {
            "ok": True,
            "count": len(matches),
            "apps": [
                {"name": e.name, "kind": e.kind, "source": e.source} for e in matches
            ],
        }

    def _open_folder(self, path: str) -> dict[str, Any]:
        problem = _valid_folder(path)
        if problem:
            return {"ok": False, "error": problem}
        candidate = _folder_target(path)
        try:
            os.startfile(str(candidate))  # noqa: S606 - cesta ověřena validátorem
        except OSError as exc:
            return {"ok": False, "error": f"Otevření složky selhalo: {exc}"}
        return {"ok": True, "path": str(candidate)}

    def _focus_window(self, title: str) -> dict[str, Any]:
        window = WindowManager.find_window(title)
        if window is None:
            return {"ok": False, "error": f"Okno '{title}' nebylo nalezeno."}
        ok = WindowManager.focus(window.hwnd)
        return {
            "ok": ok,
            "window": window.title,
            "process": window.process,
            "error": None if ok else "Okno se nepodařilo aktivovat.",
        }

    def _list_windows(self) -> dict[str, Any]:
        windows = WindowManager.list_windows()
        return {
            "ok": True,
            "count": len(windows),
            "windows": [
                {"title": w.title, "process": w.process} for w in windows[:40]
            ],
        }

    def _open_browser(self, url: str) -> dict[str, Any]:
        try:
            os.startfile(url)  # noqa: S606 - URL ověřena validátorem
        except OSError as exc:
            return {"ok": False, "error": f"Otevření prohlížeče selhalo: {exc}"}
        return {"ok": True, "url": url}

    def _open_settings(self, page: str) -> dict[str, Any]:
        target = WINDOWS_SETTINGS_PAGES.get(page.strip().lower())
        if target is None:
            return {
                "ok": False,
                "error": f"Neznámá stránka nastavení: {page}",
                "available": sorted(WINDOWS_SETTINGS_PAGES.keys()),
            }
        try:
            os.startfile(target)  # noqa: S606 - pevná mapovaná URI
        except OSError as exc:
            return {"ok": False, "error": f"Otevření nastavení selhalo: {exc}"}
        return {"ok": True, "page": page}

    def _system_stats(self) -> dict[str, Any]:
        return {"ok": True, "stats": collect_stats().to_dict()}

    def _list_audio_devices(self) -> dict[str, Any]:
        try:
            import sounddevice as sd  # type: ignore

            devices = sd.query_devices()
            inputs = [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                }
                for d in devices
                if d["max_input_channels"] > 0
            ]
            outputs = [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "channels": d["max_output_channels"],
                }
                for d in devices
                if d["max_output_channels"] > 0
            ]
            return {"ok": True, "inputs": inputs, "outputs": outputs}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Zjištění zařízení selhalo: {exc}"}

    def _set_volume(self, percent: int) -> dict[str, Any]:
        if not self._volume.available:
            return {
                "ok": False,
                "error": "Ovládání hlasitosti není v tomto systému dostupné.",
            }
        ok = self._volume.set_volume(int(percent))
        return {
            "ok": ok,
            "volume": self._volume.get_volume(),
            "error": None if ok else "Hlasitost se nepodařilo nastavit.",
        }

    def _adjust_volume(self, delta: int) -> dict[str, Any]:
        if not self._volume.available:
            return {
                "ok": False,
                "error": "Ovládání hlasitosti není v tomto systému dostupné.",
            }
        new_value = self._volume.adjust(int(delta))
        if new_value is None:
            return {"ok": False, "error": "Hlasitost se nepodařilo změnit."}
        return {"ok": True, "volume": new_value}

    def _search_memory(self, query: str) -> dict[str, Any]:
        if self._memory is None:
            return {"ok": False, "error": "Paměť není dostupná."}
        results = self._memory.search(query, limit=8)
        return {
            "ok": True,
            "count": len(results),
            "results": [
                {"content": r["content"], "category": r["category"]} for r in results
            ],
        }

    def _remember(self, content: str, category: str = "jine") -> dict[str, Any]:
        if self._memory is None:
            return {"ok": False, "error": "Paměť není dostupná."}
        entry = self._memory.remember(content, category)
        return {"ok": True, "id": entry["id"], "content": entry["content"]}

    def _set_profile(self, profile: str) -> dict[str, Any]:
        if self._hardware is None:
            return {"ok": False, "error": "Správa profilů není dostupná."}
        result = self._hardware.set_profile(profile)
        return {
            "ok": bool(result.get("ok")),
            "profile": result.get("profile"),
            "detail": result.get("detail"),
        }

    def _analyze_screen(self, question: str) -> dict[str, Any]:
        if self._vision is None:
            return {"ok": False, "error": "Modul vidění není dostupný."}
        return self._vision.analyze(question)

    # --- validátory ----------------------------------------------------
    @staticmethod
    def _validate_url(args: dict[str, Any]) -> str | None:
        url = str(args.get("url", "")).strip()
        if not url:
            return "URL není zadána."
        if not url.lower().startswith(("http://", "https://")):
            return "Povoleny jsou pouze adresy http:// a https://."
        if len(url) > 2000:
            return "URL je příliš dlouhá."
        return None

    @staticmethod
    def _validate_settings_page(args: dict[str, Any]) -> str | None:
        page = str(args.get("page", "")).strip().lower()
        if page not in WINDOWS_SETTINGS_PAGES:
            return (
                f"Neznámá stránka nastavení '{page}'. "
                f"Dostupné: {', '.join(sorted(WINDOWS_SETTINGS_PAGES))}."
            )
        return None

    @staticmethod
    def _validate_volume(args: dict[str, Any]) -> str | None:
        key = "percent" if "percent" in args else "delta"
        raw = args.get(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return f"'{key}' musí být celé číslo."
        if key == "percent" and not (0 <= value <= 100):
            return "Hlasitost musí být mezi 0 a 100."
        if key == "delta" and not (-100 <= value <= 100):
            return "Změna hlasitosti musí být mezi -100 a 100."
        return None

    @staticmethod
    def _validate_memory_text(args: dict[str, Any]) -> str | None:
        content = str(args.get("content", "")).strip()
        if not content:
            return "Obsah paměti není zadán."
        if len(content) > 2000:
            return "Obsah paměti je příliš dlouhý (max 2000 znaků)."
        return None

    @staticmethod
    def _validate_profile(args: dict[str, Any]) -> str | None:
        profile = str(args.get("profile", "")).strip().upper()
        if profile not in ("PERFORMANCE", "GAMING", "SMART"):
            return "Profil musí být PERFORMANCE, GAMING nebo SMART."
        return None
