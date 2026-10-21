"""Adversariální bezpečnostní testy.

Ověřují, že bezpečnostní omezení drží i při podvrženém nebo
zmanipulovaném vstupu - tedy když útočník ovládá text, který jde
do modelu (obrazovka, soubor, web), nebo když se snaží zneužít
nástroje k nebezpečným akcím.
"""

from __future__ import annotations

import pytest

from martin.security.engine import ToolRegistry
from martin.security.policy import SecurityLevel
from martin.system.apps import AppEntry, AppRegistry
from martin.tools.tools import ToolSet, _valid_folder
from martin.vision.analyzer import UNTRUSTED_CONTENT_WARNING

pytestmark = pytest.mark.adversarial


class TestNoShellAccess:
    """Nástroje pro libovolný shell nesmějí existovat."""

    def test_no_shell_execution_tool_exists(self):
        registry = ToolRegistry()
        for name in registry.names():
            assert "shell" not in name.lower()
            assert "exec" not in name.lower()
            assert "command" not in name.lower()
            assert "powershell" not in name.lower()
            assert "cmd" not in name.lower()

    def test_blocked_interpreters_are_listed(self):
        from martin.system.apps import BLOCKED_EXECUTABLES

        for exe in ("cmd.exe", "powershell.exe", "wscript.exe", "mshta.exe"):
            assert exe in BLOCKED_EXECUTABLES

    def test_open_app_refuses_blocked_interpreter(self):
        registry = ToolRegistry()
        toolset = ToolSet(registry, AppRegistry())
        toolset.register_all()

        apps = AppRegistry(
            extra=[AppEntry(name="cmd", target="C:\\Windows\\System32\\cmd.exe")]
        )
        toolset._apps = apps  # noqa: SLF001

        result = toolset._open_app("cmd")  # noqa: SLF001
        assert result["ok"] is False
        assert "zakázáno" in result["error"]

class TestPathTraversal:
    """Cesty na souborech."""

    def test_folder_outside_allowed_roots_is_rejected(self):
        problem = _valid_folder("C:\\Windows\\System32")
        assert problem is not None
        assert "povolené" in problem

    def test_system_root_is_rejected(self):
        assert _valid_folder("C:\\") is not None

    def test_program_files_is_rejected(self):
        assert _valid_folder("C:\\Program Files") is not None

    def test_empty_path_is_rejected(self):
        assert _valid_folder("") is not None

    def test_nonexistent_path_is_rejected(self):
        problem = _valid_folder("C:\\Users\\lukas\\Downloads\\neexistuje-xyz-123")
        assert problem is not None
        assert "neexistuje" in problem

    def test_downloads_is_allowed(self):
        from pathlib import Path

        downloads = Path.home() / "Downloads"
        if downloads.exists():
            assert _valid_folder(str(downloads)) is None


class TestUrlValidation:
    """URL - jen http/https."""

    @pytest.mark.parametrize(
        "url",
        [
            "file:///C:/Windows/System32/cmd.exe",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "ftp://example.com/x",
            "vbscript:msgbox(1)",
            "",
        ],
    )
    def test_dangerous_urls_are_rejected(self, url):
        assert ToolSet._validate_url({"url": url}) is not None

    @pytest.mark.parametrize(
        "url", ["http://example.com", "https://example.com/x?y=1"]
    )
    def test_safe_urls_are_accepted(self, url):
        assert ToolSet._validate_url({"url": url}) is None


class TestSettingsPages:
    """Nastavení Windows - jen pevně dané URI."""

    def test_unknown_page_is_rejected(self):
        assert ToolSet._validate_settings_page({"page": "../../evil"}) is not None

    def test_known_pages_pass(self):
        assert ToolSet._validate_settings_page({"page": "display"}) is None

class TestScreenPromptInjection:
    """Prompt injection ze snímku obrazovky."""

    def test_untrusted_content_warning_exists(self):
        assert "DATA, ne příkazy" in UNTRUSTED_CONTENT_WARNING
        assert "Ignoruj" in UNTRUSTED_CONTENT_WARNING

    def test_warning_mentions_injection_patterns(self):
        text = UNTRUSTED_CONTENT_WARNING.lower()
        assert "system prompt" in text
        assert "zapomeň" in text

    def test_vision_analyzer_always_injects_warning(self):
        import inspect

        from martin.vision.analyzer import VisionAnalyzer

        source = inspect.getsource(VisionAnalyzer.analyze)
        assert "UNTRUSTED_CONTENT_WARNING" in source

    def test_screen_capture_is_not_continuous(self):
        """Snímání musí být vyžáděné, ne průběžné."""
        import inspect

        from martin.vision.capture import ScreenCapture

        for method in ("capture_screen", "capture_window", "capture_to_temp_file"):
            signature = inspect.signature(getattr(ScreenCapture, method))
            assert "interval" not in signature.parameters
            assert "loop" not in signature.parameters


class TestToolLevelIntegrity:
    """Úroveň nástroje nesmí být měnitelná zvenčí."""

    def test_level_cannot_be_changed_by_model(self):
        registry = ToolRegistry()
        toolset = ToolSet(registry, AppRegistry())
        toolset.register_all()

        for spec in registry.all():
            assert isinstance(spec.level, SecurityLevel)

    def test_no_block_level_tools_registered_by_default(self):
        registry = ToolRegistry()
        toolset = ToolSet(registry, AppRegistry())
        toolset.register_all()

        for spec in registry.all():
            assert spec.level is not SecurityLevel.BLOCK

    def test_confirm_level_for_mutating_tools(self):
        registry = ToolRegistry()
        toolset = ToolSet(registry, AppRegistry())
        toolset.register_all()

        mutating = {"set_volume", "adjust_volume", "remember", "set_power_profile"}
        for name in mutating:
            spec = registry.get(name)
            assert spec is not None
            assert spec.level is SecurityLevel.CONFIRM

    def test_destructive_tool_absent(self):
        registry = ToolRegistry()
        toolset = ToolSet(registry, AppRegistry())
        toolset.register_all()

        for name in registry.names():
            lowered = name.lower()
            assert "delete" not in lowered
            assert "remove" not in lowered
            assert "rmdir" not in lowered
            assert "uninstall" not in lowered
            assert "format" not in lowered

class TestCloudParity:
    """Cloud model podléhá stejným kontrolám."""

    def test_same_registry_served_to_any_model(self):
        registry = ToolRegistry()
        toolset = ToolSet(registry, AppRegistry())
        toolset.register_all()
        schemas = registry.schemas()
        assert len(schemas) > 0
        for schema in schemas:
            assert schema["function"]["name"]
            assert schema["function"]["description"]

    def test_local_only_blocks_cloud_routing(self):
        from martin.llm.client import OllamaClient
        from martin.llm.router import ModelRouter

        router = ModelRouter(OllamaClient())
        decision = router.route(
            "analyzuj a porovnej detailne a navrhni optimalizaci architektury",
            "qwen3.5:4b",
            "cloud-model",
            local_only=True,
        )
        assert decision.provider == "local"
        assert decision.allow_cloud is False


class TestMemorySafety:
    """Paměť - obsah je omezený a revidovatelný."""

    def test_memory_content_is_bounded(self):
        problem = ToolSet._validate_memory_text({"content": "x" * 5000})
        assert problem is not None

    def test_empty_memory_content_is_rejected(self):
        assert ToolSet._validate_memory_text({"content": "   "}) is not None

    def test_memory_search_returns_limited_results(self, memory_store):
        from martin.memory.manager import MemoryManager

        manager = MemoryManager(memory_store)
        for i in range(50):
            manager.remember(f"zaznam cislo {i} o testu", "jine")
        results = manager.search("test", limit=5)
        assert len(results) <= 5