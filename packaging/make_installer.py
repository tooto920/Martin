"""Vytvoří ZIP distribuci Martina 2.1 Cloud Edition.

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
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def build_zip(build_dir: Path, out_zip: Path) -> Path:
    """Zabalí build do ZIP archivu."""
    app_dir = build_dir / "Martin"
    if not (app_dir / "Martin.exe").is_file():
        raise SystemExit(f"Nelze najít Martin.exe v {app_dir}. Nejdřív sestav build.")
    for name in (
        "whisper/ggml-small.bin",
        "vad/ggml-silero-vad.bin",
        "piper/cs_CZ-jirka-medium.onnx",
        "piper/cs_CZ-jirka-medium.onnx.json",
    ):
        if not (app_dir / "models" / name).is_file():
            raise SystemExit(
                f"Neúplný build: chybí models/{name}. Použij packaging/build_windows.py."
            )

    stage = Path(tempfile.mkdtemp(prefix="martin-stage-", dir=build_dir)) / "Martin"
    shutil.copytree(app_dir, stage)

    readme = Path(__file__).resolve().parent.parent / "docs" / "README_CLOUD_CZ.md"
    (stage.parent / "README.txt").write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")
    (stage.parent / "Spustit_Martin.bat").write_text(
        '@echo off\r\ncd /d "%~dp0Martin"\r\nstart "" Martin.exe\r\n',
        encoding="utf-8",
    )

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        raise SystemExit(f"Výstup již existuje, nic nebylo přepsáno: {out_zip}")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(stage.parent.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(stage.parent))
    stage.parent.resolve().relative_to(build_dir.resolve())
    shutil.rmtree(stage.parent, ignore_errors=True)
    return out_zip


def main() -> int:
    parser = argparse.ArgumentParser(description="Zabal Martin 2.1 Cloud do ZIP archivu.")
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
        / "Martin-2.1-Cloud-win64.zip",
    )
    args = parser.parse_args()
    path = build_zip(args.build_dir, args.out)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Hotovo: {path} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
