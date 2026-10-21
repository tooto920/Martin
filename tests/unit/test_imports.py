"""Testy, ze vsechny verejne moduly se daji naimportovat.

Tyto testy chybi Castku chyti, kdyz pri refaktoru zmizi trida
nebo funkce z nejakeho modulu (napr. PushToTalk pri prepisu
SileroVAD) - coz by jinak zustalo nezpozorovane do runtime.
"""

from __future__ import annotations

import importlib

import pytest

MODULES = [
    "martin",
    "martin.app_context",
    "martin.paths",
    "martin.__main__",
    "martin.core.logging",
    "martin.core.settings",
    "martin.hardware.monitor",
    "martin.hardware.profiles",
    "martin.llm.client",
    "martin.llm.orchestrator",
    "martin.llm.router",
    "martin.memory.conversations",
    "martin.memory.manager",
    "martin.memory.store",
    "martin.security.audit",
    "martin.security.engine",
    "martin.security.policy",
    "martin.security.redaction",
    "martin.speech.stt",
    "martin.speech.tts",
    "martin.system.apps",
    "martin.system.stats",
    "martin.system.windows",
    "martin.tools.tools",
    "martin.ui.animated",
    "martin.ui.floating",
    "martin.ui.main_window",
    "martin.ui.theme",
    "martin.ui.pages.history_page",
    "martin.ui.pages.memory_page",
    "martin.ui.pages.security_page",
    "martin.ui.pages.settings_page",
    "martin.ui.widgets.chat_view",
    "martin.ui.widgets.monitor_panel",
    "martin.ui.widgets.status_bar",
    "martin.vision.analyzer",
    "martin.vision.capture",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None


def test_stt_exposes_expected_api():
    """stt.py musi stale exportovat vsechny pouzivane symboly."""
    from martin.speech import stt

    for name in ("WhisperSTT", "AudioRecorder", "SileroVAD", "PushToTalk"):
        assert hasattr(stt, name), f"chybí {name} v martin.speech.stt"
    for name in ("AudioRecorder", "PushToTalk", "SileroVAD", "WhisperSTT"):
        assert name in stt.__all__, f"{name} není v __all__"


def test_speech_package_exports():
    from martin.speech import __all__ as speech_all

    for name in ("PiperTTS", "TTSResult", "WhisperSTT", "TranscriptionResult"):
        assert name in speech_all


def test_app_context_imports():
    """app_context musi jit naimportovat - je to hlavni skladiste."""
    module = importlib.import_module("martin.app_context")
    assert hasattr(module, "AppContext")
    assert hasattr(module, "SYSTEM_PROMPT")


def test_tools_package_exports():
    from martin.tools import __all__ as tools_all

    assert "ToolSet" in tools_all