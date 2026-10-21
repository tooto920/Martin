"""Vytvoří ZIP distribuci Martina 2.0.

ZIP obsahuje:
  Martin/Martin.exe      - spustitelná aplikace
  Martin/models/piper/   - české hlasy Piper
  Martin/models/vad/     - Silero VAD model (ONNX + whisper.cpp)
  Martin/models/whisper/ - model whisper.cpp "small" pro rozpoznání řeči
  README.txt              - krátké informace pro uživatele
  Spustit_Martin.bat      - zástupce pro spuštění
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from martin.paths import (  # noqa: E402
    PIPER_VOICES_DIR,
    VAD_MODEL_DIR,
    WHISPER_MODELS_DIR,
)

READ_ME = """\
Martin 2.0 - osobni AI asistent pro Windows 11
================================================

SPUSTENI
--------
Dvojklik na Martin.exe

POZADAVKY
---------
- Ollama musi bezet na http://127.0.0.1:11434
  (nainstalace: https://ollama.com)
- Model qwen3.5:4b doporucujeme nainstalovat:
  ollama pull qwen3.5:4b

DATA A NASTAVENI
----------------
- %LOCALAPPDATA%\\Martin\\logs\\martin.log   - log aplikace
- %LOCALAPPDATA%\\Martin\\martin.db          - dlouhodoba pamet
- %LOCALAPPDATA%\\Martin\\konverzace.db     - historie konverzaci
- %LOCALAPPDATA%\\Martin\\settings.json      - nastaveni

BEZPECNOST
----------
Martin nema pristup k shellu. Akce deleni tri urovne:
- SAFE       - jen cteni a spusteni schvalenych aplikaci
- CONFIRM    - zmenu udaju, vyzaduje vase potvrzeni
- BLOCK      - destruktivni akce jsou vzdy zablokovane
"""


def build_zip(build_dir: Path, out_zip: Path) -> Path:
    """Zabalí build do ZIP archivu."""
    app_dir = build_dir / "Martin"
    if not (app_dir / "Martin.exe").is_file():
        raise SystemExit(f"Nelze najít Martin.exe v {app_dir}. Nejdřív sestav build.")

    stage = build_dir / "_stage" / "Martin"
    if stage.exists():
        shutil.rmtree(stage)
    stage.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app_dir, stage)

    # Modely Piper a VAD - zkopirovat vedle exe.
    # Modely whisper.cpp - pouze vychozi "small". Ostatni (base, tiny)
    # jsou volitelne a daji se stahnout rucne - jinak by distribuce
    # merila pres 1.4 GB.
    #
    # POZOR: model se nekopiruje vedle exe, pokud je uz v _internal
    # (PyInstaller ho tam balil) - jinak by byl v distribuci dvakrat.
    whisper_src = WHISPER_MODELS_DIR / "ggml-small.bin"
    internal_model = stage / "_internal" / "models" / "whisper" / whisper_src.name
    if whisper_src.is_file() and not internal_model.is_file():
        whisper_dir = stage / "models" / "whisper"
        whisper_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(whisper_src, whisper_dir / whisper_src.name)

    for src, rel in (
        (PIPER_VOICES_DIR, "models/piper"),
        (VAD_MODEL_DIR, "models/vad"),
    ):
        if not src.is_dir():
            continue
        dest = stage.joinpath(*rel.split("/"))
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.is_file():
                shutil.copy2(item, dest / item.name)

    (stage.parent / "README.txt").write_text(READ_ME, encoding="utf-8")
    (stage.parent / "Spustit_Martin.bat").write_text(
        "@echo off\r\n"
        "cd /d \"%~dp0Martin\"\r\n"
        "start \"\" Martin.exe\r\n",
        encoding="utf-8",
    )

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(stage.parent.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(stage.parent))
    shutil.rmtree(stage.parent, ignore_errors=True)
    return out_zip


def main() -> int:
    parser = argparse.ArgumentParser(description="Zabal Martin 2.0 do ZIP archivu.")
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "build_output",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "build_output"
        / "Martin-2.0-win64.zip",
    )
    args = parser.parse_args()
    path = build_zip(args.build_dir, args.out)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Hotovo: {path} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())