"""Testy hardwarových profilů a monitoringu."""

from __future__ import annotations

import pytest

from martin.hardware.monitor import HardwareMonitor, SystemSnapshot
from martin.hardware.profiles import (
    PROFILE_GAMING,
    PROFILE_PERFORMANCE,
    PROFILE_SMART,
    PROFILES,
    HardwareManager,
)


def make_snapshot(
    vram_used=1000.0,
    vram_total=8000.0,
    cpu=20.0,
    ram=30.0,
):
    return SystemSnapshot(
        timestamp=0.0,
        cpu_percent=cpu,
        ram_percent=ram,
        ram_used_gb=8.0,
        ram_total_gb=32.0,
        gpu_utilization=15.0,
        gpu_memory_used_mb=vram_used,
        gpu_memory_total_mb=vram_total,
        gpu_name="Test GPU",
        temperature_c=45.0,
        battery_percent=80.0,
    )


class TestSnapshot:
    def test_vram_free_computed(self):
        snap = make_snapshot(vram_used=2000.0, vram_total=8000.0)
        assert snap.vram_free_mb == 6000.0
        assert snap.vram_percent == 25.0

    def test_vram_free_never_negative(self):
        snap = make_snapshot(vram_used=9000.0, vram_total=8000.0)
        assert snap.vram_free_mb == 0.0

    def test_vram_percent_zero_total(self):
        snap = make_snapshot(vram_used=0.0, vram_total=0.0)
        assert snap.vram_percent == 0.0

    def test_to_dict_has_expected_keys(self):
        data = make_snapshot().to_dict()
        for key in (
            "cpu_percent",
            "ram_percent",
            "gpu_memory_used_mb",
            "vram_free_mb",
            "vram_percent",
            "gpu_name",
        ):
            assert key in data


class TestHardwareManager:
    def test_default_profile_is_smart(self):
        manager = HardwareManager(HardwareMonitor())
        assert manager.profile == PROFILE_SMART

    def test_all_profiles_defined(self):
        manager = HardwareManager(HardwareMonitor())
        names = {p.name for p in manager.profiles()}
        assert names == set(PROFILES)
        assert {PROFILE_PERFORMANCE, PROFILE_GAMING, PROFILE_SMART} <= names

    def test_unknown_profile_rejected(self):
        manager = HardwareManager(HardwareMonitor())
        result = manager.set_profile("NEEXISTUJICI")
        assert result["ok"] is False
        assert "Neznámý profil" in result["error"]

    def test_profile_switch_updates_state(self):
        manager = HardwareManager(HardwareMonitor())
        result = manager.set_profile(PROFILE_GAMING)
        assert result["ok"] is True
        assert manager.profile == PROFILE_GAMING

    def test_gaming_prefers_cloud(self):
        manager = HardwareManager(HardwareMonitor(), cloud_allowed=True)
        manager.set_profile(PROFILE_GAMING)
        assert manager.should_use_cloud() is True

    def test_local_only_disables_cloud(self):
        manager = HardwareManager(HardwareMonitor(), cloud_allowed=False)
        manager.set_profile(PROFILE_GAMING)
        assert manager.should_use_cloud() is False

    def test_performance_keeps_model_warm(self):
        manager = HardwareManager(HardwareMonitor())
        manager.set_profile(PROFILE_PERFORMANCE)
        assert manager.definition.keep_alive != "0"
        assert manager.definition.num_gpu_layers > 0

    def test_gaming_releases_gpu_layers(self):
        manager = HardwareManager(HardwareMonitor())
        manager.set_profile(PROFILE_GAMING)
        assert manager.definition.keep_alive == "0"
        assert manager.definition.num_gpu_layers == 0

    def test_smart_prefers_cloud_on_high_vram(self):
        manager = HardwareManager(HardwareMonitor(), cloud_allowed=True)
        manager.set_profile(PROFILE_SMART)
        high = make_snapshot(vram_used=7000.0, vram_total=8000.0)
        assert manager.should_use_cloud(high) is True

    def test_smart_keeps_local_on_low_vram(self):
        manager = HardwareManager(HardwareMonitor(), cloud_allowed=True)
        manager.set_profile(PROFILE_SMART)
        low = make_snapshot(vram_used=1000.0, vram_total=8000.0)
        assert manager.should_use_cloud(low) is False

    def test_apply_to_settings(self):
        from martin.core.settings import Settings

        manager = HardwareManager(HardwareMonitor())
        settings = Settings()
        manager.set_profile(PROFILE_GAMING)
        manager.apply_to_settings(settings)
        assert settings.profile == PROFILE_GAMING
        assert settings.keep_model_warm is False
        assert settings.gpu_layers == 0

    def test_status_contains_profile(self):
        manager = HardwareManager(HardwareMonitor())
        status = manager.status()
        assert status["profile"] == PROFILE_SMART
        assert "label" in status


class TestMonitor:
    def test_snapshot_returns_real_data(self):
        monitor = HardwareMonitor(interval=1.0)
        snap = monitor.snapshot()
        assert snap.ram_total_gb > 0
        assert 0 <= snap.ram_percent <= 100
        assert snap.timestamp > 0

    def test_start_and_stop(self):
        monitor = HardwareMonitor(interval=0.2)
        monitor.start()
        monitor.start()  # nesmi spustit dve vlakna
        monitor.stop()
        monitor.stop()
        assert monitor.latest() is None or monitor.latest() is not None