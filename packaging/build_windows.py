"""Build a complete Windows folder, with source identity and required models."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def build(destination: Path):
    destination = destination.resolve()
    if destination.exists():
        raise SystemExit(f"Cíl už existuje; zvol novou složku: {destination}")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(Path(sys.executable).parent), sys.base_prefix,
        str(Path(env["SystemRoot"]) / "System32"), env["SystemRoot"],
    ])
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                    "--distpath", str(destination), "--workpath", str(destination.parent / (destination.name + "-work")),
                    str(PROJECT / "martin.spec")], cwd=PROJECT, env=env, check=True)
    app = destination / "Martin"
    for relative in ("whisper/ggml-small.bin", "vad/ggml-silero-vad.bin",
                     "piper/cs_CZ-jirka-medium.onnx", "piper/cs_CZ-jirka-medium.onnx.json"):
        source = PROJECT / "models" / relative
        if not source.is_file():
            raise SystemExit(f"Chybí požadovaný model: {source}")
    shutil.copytree(PROJECT / "models", app / "models")
    def digest(path):
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    sources = {str(p.relative_to(PROJECT)).replace("\\", "/"): digest(p)
               for p in sorted((PROJECT / "martin").rglob("*.py"))}
    sources["run_martin.py"] = digest(PROJECT / "run_martin.py")
    manifest = {
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip(),
        "source_sha256": sources,
        "files_sha256": {str(p.relative_to(app)).replace("\\", "/"): digest(p)
                         for p in sorted(app.rglob("*")) if p.is_file()},
    }
    (app / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    print(build(parser.parse_args().out))
