"""Testy routování, nastavení a objevu aplikací."""

from __future__ import annotations

from martin.core.settings import Settings, SettingsStore
from martin.llm.router import ModelRouter, TaskComplexity
from martin.system.apps import AppRegistry, _norm


class FakeClient:
    """Náhrada OllamaClientu pro testy routování."""

    def __init__(self, vision=True, tools=True):
        self._vision = vision
        self._tools = tools

    def has_vision(self, name):
        return self._vision

    def has_tools(self, name):
        return self._tools

    def is_available(self):
        return True

    def model_names(self):
        return ["qwen3.5:4b", "some:cloud"]


class TestRouter:
    def test_simple_request_uses_cloud(self):
        router = ModelRouter(FakeClient())
        decision = router.route("ahoj, jak se máš?", "local", "some:cloud")
        assert decision.provider == "cloud"
        assert decision.model == "some:cloud"

    def test_vision_request_uses_vision_model(self):
        router = ModelRouter(FakeClient())
        decision = router.route("Co je na obrazovce?", "local", "some:cloud")
        assert decision.requires_vision is True
        assert decision.provider == "cloud"

    def test_complex_request_goes_to_cloud(self):
        router = ModelRouter(FakeClient())
        decision = router.route(
            "analyzuj a porovnej detailne a navrhni optimalizaci architektury",
            "local",
            "some:cloud",
        )
        assert decision.provider == "cloud"

    def test_local_only_never_uses_cloud(self):
        router = ModelRouter(FakeClient())
        decision = router.route(
            "analyzuj a porovnej detailne architekturu a navrhni optimalizaci",
            "local",
            "cloud",
            local_only=True,
        )
        assert decision.provider == "local"
        assert decision.allow_cloud is False

    def test_local_only_with_non_vision_model_raises(self):
        router = ModelRouter(FakeClient(vision=False))
        try:
            router.route("Co je na obrazovce?", "local", "cloud", local_only=True)
        except ValueError as exc:
            assert "obraz" in str(exc)
        else:
            raise AssertionError("Očekávána výjimka ValueError")

    def test_complexity_estimation(self):
        router = ModelRouter(FakeClient())
        assert router.estimate_complexity("ahoj") is TaskComplexity.TRIVIAL
        assert router.estimate_complexity("analyzuj a porovnej a navrhni") is TaskComplexity.COMPLEX

    def test_tool_request_detected(self):
        router = ModelRouter(FakeClient())
        assert router.requires_tools("spusť mi Microsoft Flight Simulator") is True
        assert router.requires_tools("ahoj") is False

    def test_vision_marker_detected(self):
        router = ModelRouter(FakeClient())
        assert router.requires_vision("co je tohle?") is True


class TestSettings:
    def test_defaults_are_sane(self):
        settings = Settings()
        assert settings.local_model == "qwen3.5:4b"
        assert settings.local_only is False
        assert settings.profile == "SMART"
        assert settings.theme == "dark"

    def test_save_and_load_roundtrip(self, settings_store):
        settings_store.update(local_model="test-model", temperature=0.9)
        reloaded = SettingsStore(settings_store.path)
        assert reloaded.settings.local_model == "test-model"
        assert reloaded.settings.temperature == 0.9

    def test_update_ignores_unknown_keys_but_keeps_extra(self, settings_store):
        settings_store.update(custom_key="hodnota")
        assert settings_store.settings.extra["custom_key"] == "hodnota"

    def test_corrupt_file_falls_back_to_defaults(self, temp_dir):
        path = temp_dir / "settings.json"
        path.write_text("{ to neni json", encoding="utf-8")
        store = SettingsStore(path)
        assert store.settings.local_model == "qwen3.5:4b"

    def test_reset_restores_defaults(self, settings_store):
        settings_store.update(temperature=1.9)
        settings_store.reset()
        assert settings_store.settings.temperature == 0.6

    def test_save_is_atomic(self, settings_store):
        settings_store.update(temperature=0.3)
        assert settings_store.save() is True
        assert not list(settings_store.path.parent.glob("*.tmp"))


class TestAppDiscovery:
    def test_normalization_strips_diacritics(self):
        assert _norm("Příliš žluťoučký") == "prilis zlutoucky"
        assert _norm("Český") == "cesky"

    def test_registry_finds_known_app(self):
        registry = AppRegistry()
        entry = registry.find("Steam")
        assert entry is not None
        assert "steam" in entry.kind or "steam" in entry.name.lower()

    def test_registry_search_returns_list(self):
        registry = AppRegistry()
        results = registry.search("code", limit=5)
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_unknown_app_returns_none(self):
        registry = AppRegistry()
        assert registry.find("xyz-neexistuje-12345") is None

    def test_empty_query_returns_none(self):
        registry = AppRegistry()
        assert registry.find("") is None
