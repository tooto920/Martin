"""Objevování nainstalovaných aplikací a her.

Strategie (v pořadí spolehlivosti):
  1. Windows App Paths v registru
  2. Klíče odinstalace (Uninstall) - InstallLocation
  3. Zástupci v nabídce Start (.lnk / .url) - rozlišení přes COM
  4. Pevně dané lokace pro Steam a běžné programy
  5. Steam hry z appmanifest_*.acf

Cílem je nikdy neuhádat cestu k exe - buď ji najdeme, nebo aplikaci
spustit nelze a uživatel dostane srozumitelnou hlášku.
"""

from __future__ import annotations

import os
import re
import winreg
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from martin.core.logging import get_logger

log = get_logger("martin.system.apps")

# Bezpečná rozšíření, která lze spustit.
EXECUTABLE_EXTENSIONS = (".exe", ".lnk", ".bat", ".cmd", ".url", ".msc")

UNINSTALL_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)

STEAM_PATHS = (
    Path(r"C:\Program Files (x86)\Steam"),
    Path(r"C:\Program Files\Steam"),
)

KNOWN_APPS: dict[str, list[str]] = {
    "visual studio code": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "vscode": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "discord": [
        r"%LOCALAPPDATA%\Discord\Update.exe",
        r"C:\Program Files\Discord\Discord.exe",
    ],
    "notepad": [r"C:\Windows\System32\notepad.exe"],
    "explorer": [r"C:\Windows\explorer.exe"],
    "powershell": [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"],
    "terminal": [r"C:\Windows\System32\WindowsTerminal\wt.exe"],
    "cmd": [r"C:\Windows\System32\cmd.exe"],
    "paint": [r"C:\Windows\System32\mspaint.exe"],
    "calculator": [r"C:\Windows\System32\calc.exe"],
}

# Aplikace, které nesmí být spuštěny přes nástroj (bezpečnostní riziko).
BLOCKED_EXECUTABLES = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "wscript.exe",
        "cscript.exe",
        "mshta.exe",
        "regsvr32.exe",
        "rundll32.exe",
    }
)


@dataclass(slots=True)
class AppEntry:
    """Nalezená aplikace."""

    name: str
    target: str
    kind: str = "executable"  # executable | steam | url | folder
    source: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_blocked(self) -> bool:
        return Path(self.target).name.lower() in BLOCKED_EXECUTABLES

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "target": self.target,
            "kind": self.kind,
            "source": self.source,
        }


def _norm(text: str) -> str:
    """Normalizuje název pro porovnání (bez diakritiky, malá písmena)."""
    folded = (
        text.lower()
        .replace("ě", "e").replace("š", "s").replace("č", "c")
        .replace("ř", "r").replace("ž", "z").replace("ý", "y")
        .replace("á", "a").replace("í", "i").replace("é", "e")
        .replace("ú", "u").replace("ů", "u").replace("ď", "d")
        .replace("ť", "t").replace("ň", "n")
    )
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser()


def _read_app_paths() -> list[AppEntry]:
    """Windows App Paths - nejspolehlivější zdroj cest k exe."""
    entries: list[AppEntry] = []
    for hive, key_path in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, name) as sub:
                            value, _ = winreg.QueryValueEx(sub, "")
                            if value:
                                entries.append(
                                    AppEntry(
                                        name=name.replace(".exe", ""),
                                        target=str(value),
                                        kind="executable",
                                        source="App Paths",
                                    )
                                )
                    except OSError:
                        continue
        except OSError:
            continue
    return entries


def _read_uninstall() -> list[AppEntry]:
    """Klíče odinstalace - hodnoty InstallLocation."""
    entries: list[AppEntry] = []
    for hive, key_path in UNINSTALL_KEYS:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                index = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, sub_name) as sub:
                            try:
                                display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                            except OSError:
                                continue
                            try:
                                location = str(winreg.QueryValueEx(sub, "InstallLocation")[0])
                            except OSError:
                                location = ""
                            if location:
                                entries.append(
                                    AppEntry(
                                        name=display,
                                        target=location,
                                        kind="folder",
                                        source="Uninstall",
                                    )
                                )
                    except OSError:
                        continue
        except OSError:
            continue
    return entries


def _start_menu_dirs() -> list[Path]:
    dirs = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    return [d for d in dirs if d.is_dir()]


def _resolve_shortcut(path: Path) -> str | None:
    """Rozliší zástupce .lnk / .url na skutečný cíl."""
    try:
        if path.suffix.lower() == ".url":
            text = path.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"URL=([^\r\n]+)", text)
            return match.group(1).strip() if match else None
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(path))
        return shortcut.TargetPath or None
    except Exception:  # noqa: BLE001 - COM může být nedostupný
        return None


def _read_start_menu() -> list[AppEntry]:
    """Zástupci z nabídky Start."""
    entries: list[AppEntry] = []
    for directory in _start_menu_dirs():
        try:
            for item in directory.rglob("*"):
                if item.suffix.lower() not in (".lnk", ".url"):
                    continue
                target = _resolve_shortcut(item)
                if not target:
                    continue
                kind = "url" if item.suffix.lower() == ".url" else "executable"
                entries.append(
                    AppEntry(
                        name=item.stem,
                        target=target,
                        kind=kind,
                        source="Start Menu",
                    )
                )
        except OSError:
            continue
    return entries


def _steam_library() -> Path | None:
    for base in STEAM_PATHS:
        if (base / "steam.exe").is_file():
            return base
    return None


def _read_steam_games() -> list[AppEntry]:
    """Hry nainstalované přes Steam."""
    entries: list[AppEntry] = []
    base = _steam_library()
    if base is None:
        return entries
    apps_dir = base / "steamapps"
    if not apps_dir.is_dir():
        return entries
    for manifest in apps_dir.glob("appmanifest_*.acf"):
        appid = manifest.stem.replace("appmanifest_", "")
        name = appid
        try:
            text = manifest.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r'"name"\s+"([^"]+)"', text)
            if match:
                name = match.group(1)
        except OSError:
            pass
        entries.append(
            AppEntry(
                name=name,
                target=f"steam://rungameid/{appid}",
                kind="steam",
                source="Steam",
                aliases=(appid,),
            )
        )
    return entries


def _known_apps() -> list[AppEntry]:
    """Předdefinované lokace pro běžné programy."""
    entries: list[AppEntry] = []
    for label, paths in KNOWN_APPS.items():
        for raw in paths:
            candidate = _expand(raw)
            if candidate.is_file():
                entries.append(
                    AppEntry(
                        name=label,
                        target=str(candidate),
                        kind="executable",
                        source="known",
                    )
                )
                break
    return entries


@lru_cache(maxsize=1)
def discover_apps() -> tuple[AppEntry, ...]:
    """Najde všechny dostupné aplikace (s cache)."""
    found: list[AppEntry] = []
    for producer in (
        _known_apps,
        _read_app_paths,
        _read_steam_games,
        _read_start_menu,
        _read_uninstall,
    ):
        try:
            found.extend(producer())
        except Exception as exc:  # noqa: BLE001 - objev nesmí shodit běh
            log.warning("Objev aplikací selhal u %s: %s", producer.__name__, exc)
    # Deduplikace podle normalizovaného názvu, první nález má přednost.
    seen: set[str] = set()
    unique: list[AppEntry] = []
    for entry in found:
        key = _norm(entry.name)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return tuple(unique)


class AppRegistry:
    """Vyhledávání a spouštění aplikací."""

    def __init__(self, extra: list[AppEntry] | None = None) -> None:
        self._extra = list(extra or [])

    def set_extra(self, entries: list[AppEntry]) -> None:
        self._extra = list(entries)

    def all(self) -> list[AppEntry]:
        return list(self._extra) + list(discover_apps())

    def find(self, query: str) -> AppEntry | None:
        """Najde aplikaci podle názvu (fuzzy, bez diakritiky)."""
        needle = _norm(query)
        if not needle:
            return None
        entries = self.all()
        # 1) Přesná shoda normalizovaného názvu.
        for entry in entries:
            if _norm(entry.name) == needle:
                return entry
        # 2) Shoda aliasu (např. Steam appid).
        for entry in entries:
            if any(_norm(a) == needle for a in entry.aliases):
                return entry
        # 3) Prefix.
        for entry in entries:
            name = _norm(entry.name)
            if name.startswith(needle) or needle.startswith(name):
                return entry
        # 4) Podřetězec.
        for entry in entries:
            if needle in _norm(entry.name):
                return entry
        return None

    def search(self, query: str, limit: int = 20) -> list[AppEntry]:
        """Vrátí aplikace odpovídající dotazu."""
        needle = _norm(query)
        if not needle:
            return self.all()[:limit]
        matches = [e for e in self.all() if needle in _norm(e.name)]
        return matches[:limit]

    def resolve_target(self, entry: AppEntry) -> Path | None:
        """Vrátí existující cestu, pokud je aplikace typu soubor."""
        if entry.kind == "steam" or entry.kind == "url":
            return None
        target = Path(entry.target)
        if target.is_file():
            return target
        if target.is_dir():
            for candidate in target.rglob("*.exe"):
                if candidate.is_file():
                    return candidate
        return None