"""Monitorování reálného využití CPU, RAM, VRAM a teploty.

Důležité: Martin NESMÍ tvrdit, že paměť byla uvolněna, aniž by to
skutečně ověřil. Všechny hodnoty se čtou z reálného systému."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import psutil

from martin.system.stats import collect_stats


@dataclass(slots=True)
class SystemSnapshot:
    """Snapshot systémových zdrojů v jednom okamžiku."""

    timestamp: float
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    gpu_utilization: float
    gpu_memory_used_mb: float
    gpu_memory_total_mb: float
    gpu_name: str
    temperature_c: float | None
    battery_percent: float | None

    @property
    def vram_free_mb(self) -> float:
        return max(0.0, self.gpu_memory_total_mb - self.gpu_memory_used_mb)

    @property
    def vram_percent(self) -> float:
        if not self.gpu_memory_total_mb:
            return 0.0
        return (self.gpu_memory_used_mb / self.gpu_memory_total_mb) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cpu_percent": round(self.cpu_percent, 1),
            "ram_percent": round(self.ram_percent, 1),
            "ram_used_gb": round(self.ram_used_gb, 2),
            "ram_total_gb": round(self.ram_total_gb, 2),
            "gpu_utilization": round(self.gpu_utilization, 0),
            "gpu_memory_used_mb": round(self.gpu_memory_used_mb, 0),
            "gpu_memory_total_mb": round(self.gpu_memory_total_mb, 0),
            "vram_free_mb": round(self.vram_free_mb, 0),
            "vram_percent": round(self.vram_percent, 1),
            "gpu_name": self.gpu_name,
            "temperature_c": self.temperature_c,
            "battery_percent": self.battery_percent,
        }


class HardwareMonitor:
    """Pravidelně sbírá snapshoty systémových zdrojů."""

    def __init__(self, interval: float = 2.0) -> None:
        self._interval = interval
        self._lock = threading.RLock()
        self._latest: SystemSnapshot | None = None
        self._callbacks: list[Callable[[SystemSnapshot], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add_callback(self, callback: Callable[[SystemSnapshot], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def latest(self) -> SystemSnapshot | None:
        with self._lock:
            return self._latest

    def snapshot(self) -> SystemSnapshot:
        """Okamžitý snapshot systémových zdrojů."""
        stats = collect_stats()
        return SystemSnapshot(
            timestamp=time.time(),
            cpu_percent=stats.cpu_percent,
            ram_percent=stats.ram_percent,
            ram_used_gb=stats.ram_used_gb,
            ram_total_gb=stats.ram_total_gb,
            gpu_utilization=stats.gpu_utilization,
            gpu_memory_used_mb=stats.gpu_memory_used_mb,
            gpu_memory_total_mb=stats.gpu_memory_total_mb,
            gpu_name=stats.gpu_name,
            temperature_c=stats.temperature_c,
            battery_percent=stats.battery_percent,
        )

    def start(self) -> None:
        """Spustí smyčku monitorování v pozadí."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="martin-hw-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None

    def _run(self) -> None:
        psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            try:
                snapshot = self.snapshot()
            except Exception:  # noqa: BLE001 - monitoring nesmí shodit běh
                self._stop.wait(self._interval)
                continue
            with self._lock:
                self._latest = snapshot
                callbacks = list(self._callbacks)
            for callback in callbacks:
                try:
                    callback(snapshot)
                except Exception:  # noqa: BLE001
                    pass
            self._stop.wait(self._interval)