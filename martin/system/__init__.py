"""Systémová vrstva Martina - práce s Windows."""

from martin.system.apps import AppRegistry, AppEntry, discover_apps
from martin.system.windows import WindowManager, VolumeController
from martin.system.stats import SystemStats, collect_stats

__all__ = [
    "AppRegistry",
    "AppEntry",
    "discover_apps",
    "WindowManager",
    "VolumeController",
    "SystemStats",
    "collect_stats",
]