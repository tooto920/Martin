"""Sběr bezpečných systémových statistik (read-only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psutil


@dataclass(slots=True)
class SystemStats:
    """Snapshot systémových zdrojů."""

    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    disk_percent: float
    disk_free_gb: float
    battery_percent: float | None
    battery_plugged: bool | None
    gpu_name: str
    gpu_memory_used_mb: float
    gpu_memory_total_mb: float
    gpu_utilization: float
    temperature_c: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "ram_percent": round(self.ram_percent, 1),
            "ram_used_gb": round(self.ram_used_gb, 2),
            "ram_total_gb": round(self.ram_total_gb, 2),
            "disk_percent": round(self.disk_percent, 1),
            "disk_free_gb": round(self.disk_free_gb, 1),
            "battery_percent": self.battery_percent,
            "battery_plugged": self.battery_plugged,
            "gpu_name": self.gpu_name,
            "gpu_memory_used_mb": round(self.gpu_memory_used_mb, 0),
            "gpu_memory_total_mb": round(self.gpu_memory_total_mb, 0),
            "gpu_utilization": round(self.gpu_utilization, 0),
            "temperature_c": self.temperature_c,
        }

    def summary_cz(self) -> str:
        """Krátký český popis stavu systému."""
        parts = [
            f"CPU {self.cpu_percent:.0f} %",
            f"RAM {self.ram_percent:.0f} %",
            f"GPU {self.gpu_utilization:.0f} %",
        ]
        if self.gpu_memory_total_mb:
            parts.append(
                f"VRAM {self.gpu_memory_used_mb:.0f}/{self.gpu_memory_total_mb:.0f} MB"
            )
        return ", ".join(parts)


def _gpu_stats() -> tuple[str, float, float, float, float | None]:
    """Údaje o GPU přes nvidia-smi (pokud je dostupné)."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                name = parts[0]
                used = float(parts[1])
                total = float(parts[2])
                util = float(parts[3])
                temp = float(parts[4]) if len(parts) > 4 and parts[4] else None
                return name, used, total, util, temp
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "", 0.0, 0.0, 0.0, None


def collect_stats() -> SystemStats:
    """Sběhne aktuální systémové statistiky."""
    virtual = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    battery_percent: float | None = None
    plugged: bool | None = None
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            battery_percent = float(battery.percent)
            plugged = bool(battery.power_plugged)
    except (AttributeError, OSError):
        pass

    gpu_name, gpu_used, gpu_total, gpu_util, gpu_temp = _gpu_stats()

    return SystemStats(
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_percent=float(virtual.percent),
        ram_used_gb=virtual.used / (1024**3),
        ram_total_gb=virtual.total / (1024**3),
        disk_percent=float(disk.percent),
        disk_free_gb=disk.free / (1024**3),
        battery_percent=battery_percent,
        battery_plugged=plugged,
        gpu_name=gpu_name,
        gpu_memory_used_mb=gpu_used,
        gpu_memory_total_mb=gpu_total,
        gpu_utilization=gpu_util,
        temperature_c=gpu_temp,
    )
