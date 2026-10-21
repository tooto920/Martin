"""Správa hardwarových profilů a monitoring zdrojů."""

from martin.hardware.monitor import HardwareMonitor, SystemSnapshot
from martin.hardware.profiles import (
    HardwareManager,
    PowerProfile,
    PROFILE_PERFORMANCE,
    PROFILE_GAMING,
    PROFILE_SMART,
)

__all__ = [
    "HardwareMonitor",
    "SystemSnapshot",
    "HardwareManager",
    "PowerProfile",
    "PROFILE_PERFORMANCE",
    "PROFILE_GAMING",
    "PROFILE_SMART",
]