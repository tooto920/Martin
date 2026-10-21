# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specifikace pro Martin 2.0.

Vysledek: build_output/Martin/Martin.exe (onedir - rychlejsi start
a jednoduchsi pristup k modelum Piper vedle exe).
"""

import os
import sys
from pathlib import Path

PROJECT = Path(SPECPATH)
MODELS = PROJECT / "models"
# Build tools inherit PATH from their host. Foreign libheif/poppler CRT
# shims must not override the Windows 11 runtime or Qt DLL resolution.
os.environ["PATH"] = os.pathsep.join([
    str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
    str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"],
])

# Modely Piper jsou vetsi nez 60 MB - pri baleni dovnitr exe by build
# trval neumerousne dlouho a exe by narostlo. Radji je nechame
# vedle v adresari models/ a pri instalaci je zkopirujeme.
datas = []
if (MODELS / "vad" / "silero_vad.onnx").is_file():
    datas.append((str(MODELS / "vad" / "silero_vad.onnx"), "models/vad"))
if (MODELS / "vad" / "ggml-silero-vad.bin").is_file():
    datas.append((str(MODELS / "vad" / "ggml-silero-vad.bin"), "models/vad"))
# Model whisper.cpp se NEUMIST'uje dovnitr - je 465 MB a instalator
# ho kopiruje vedle exe. Tady by se duplikoval (2x v distribuci).

icon_path = PROJECT / "packaging" / "martin.ico"
icon = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(PROJECT / "run_martin.py")],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Piper bezi in-proces (piper.PiperVoice) - bez toho by
        # aplikace ve zabalene podobe nemela syntetyzu.
        "piper",
        "piper.voice",
        "piper.config",
        "piper.phonemize_espeak",
        # whisper.cpp - nahrada faster-whisper (blokovana WDAC).
        "pywhispercpp",
        "pywhispercpp.model",
        "_pywhispercpp",
        "sounddevice",
        "mss",
        "onnxruntime",
        "win32com.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # faster-whisper je blokovan zasadou WDAC (av/logging.pyd).
        "faster_whisper",
        "tkinter",
        "matplotlib",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtBluetooth",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtPdf",
        "PySide6.QtPositioning",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtStateMachine",
        "PySide6.QtSvgWidgets",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Martin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Martin",
)
