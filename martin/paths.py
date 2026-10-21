"""Konfigurace a cesty aplikace Martin 2.0.

Všechny cesty se odvozují z adresáře dat, aby šla aplikace zabalit do
jediné složky (PyInstaller) bez zásahů do kódu.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Martin"
APP_VERSION = "2.0.0"
ORG_NAME = "Martin"


def _base_dir() -> Path:
    """Kořen aplikace - kompatibilní s PyInstaller onefile i onedir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """Adresář pro data uživatele (databáze, logy, nastavení)."""
    override = os.environ.get("MARTIN_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    return _base_dir() / "data"


def _models_dir() -> Path:
    """Adresář s modely (Piper hlasy, Silero VAD).

    PyInstaller (onedir) umisťuje balená data do `_internal`, ale
    instalace ZIP je umisťuje vedle exe. Proto se kontrolují oba
    varianty a vrací se ten, který existuje.
    """
    override = os.environ.get("MARTIN_MODELS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        base = _base_dir()
        candidates = [
            base / "models",
            Path(getattr(sys, "_MEIPASS", base)) / "models",
            base / "_internal" / "models",
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]
    return _base_dir() / "models"


BASE_DIR = _base_dir()
DATA_DIR = _data_dir()
MODELS_DIR = _models_dir()

DB_PATH = DATA_DIR / "martin.db"
# Databaze konverzaci je zvlastni, aby se nesmysla s pameti.
CONVERSATIONS_DB_PATH = DATA_DIR / "konverzace.db"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_PATH = DATA_DIR / "settings.json"
SECURITY_LOG_PATH = DATA_DIR / "logs" / "security.jsonl"
PIPER_VOICES_DIR = MODELS_DIR / "piper"
VAD_MODEL_DIR = MODELS_DIR / "vad"
VAD_MODEL_PATH = VAD_MODEL_DIR / "silero_vad.onnx"
WHISPER_CACHE_DIR = MODELS_DIR / "whisper"

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen3.5:4b"
DEFAULT_CLOUD_MODEL = "nemotron-3-nano:30b-cloud"

# Kandidáti na české hlasy Piper (v pořadí preference).
PIPER_VOICE_CANDIDATES = (
    "cs_CZ-jirka-medium",
    "cs_CZ-kasandra-medium",
)


def ensure_dirs() -> None:
    """Vytvoří potřebné adresáře, pokud ještě neexistují."""
    for path in (DATA_DIR, LOG_DIR, PIPER_VOICES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _piper_search_dirs() -> list[Path]:
    """Adresáře, ve kterých se hledají české hlasy Piper."""
    dirs = [PIPER_VOICES_DIR]
    if getattr(sys, "frozen", False):
        base = _base_dir()
        for extra in (
            base / "models" / "piper",
            base / "_internal" / "models" / "piper",
            Path(getattr(sys, "_MEIPASS", base)) / "models" / "piper",
        ):
            if extra not in dirs:
                dirs.append(extra)
    return dirs


def find_piper_voice(name: str | None = None) -> Path | None:
    """Najde soubor .onnx českého Piper hlasu.

    Vrací cestu k modelu, nebo None pokud není dostupný žádný hlas.
    """
    dirs = _piper_search_dirs()
    if name:
        for directory in dirs:
            candidate = directory / f"{name}.onnx"
            if candidate.is_file():
                return candidate
        return None
    for stem in PIPER_VOICE_CANDIDATES:
        for directory in dirs:
            candidate = directory / f"{stem}.onnx"
            if candidate.is_file():
                return candidate
    return None