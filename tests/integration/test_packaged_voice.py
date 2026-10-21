"""Opt-in, real EXE + hardware check; never reported as tested when skipped.

Set MARTIN_TEST_PACKAGED_EXE to an absolute path to a complete built folder.
The executable captures the default mic and plays fixed Czech sentences.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.integration
def test_packaged_exe_models_native_startup_voice_and_shutdown(tmp_path):
    configured = os.environ.get("MARTIN_TEST_PACKAGED_EXE")
    if not configured:
        pytest.skip("Real EXE/hardware test requires MARTIN_TEST_PACKAGED_EXE")
    exe = Path(configured).resolve(strict=True)
    manifest = json.loads((exe.parent / "build-manifest.json").read_text(encoding="utf-8"))
    for name in ("phontab", "phondata", "phonindex", "cs_dict", "lang/zlw/cs"):
        assert (exe.parent / "_internal/piper/espeak-ng-data" / name).is_file(), name
    for name, expected in manifest["files_sha256"].items():
        path = (exe.parent / name).resolve(strict=True)
        path.relative_to(exe.parent)
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        assert actual == expected, name
    env = os.environ.copy()
    env["MARTIN_DATA_DIR"] = str(tmp_path / "isolated-data")
    env.pop("MARTIN_MODELS_DIR", None)
    report = tmp_path / "hardware-report.json"
    result = subprocess.run([str(exe), "--diagnose-voice", str(report), "12"],
                            env=env, cwd=tmp_path, timeout=180, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert report.is_file(), f"EXE did not produce diagnostics (exit {result.returncode})"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert result.returncode == 0, data
    assert data["errors"] == [], data
    assert data["checks"] and all(c["ok"] for c in data["checks"].values()), data
    destination = os.environ.get("MARTIN_PACKAGED_REPORT_OUT")
    if destination:
        Path(destination).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
