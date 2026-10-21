"""Správa oken a hlasitosti ve Windows."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Any

from martin.core.logging import get_logger

log = get_logger("martin.system.windows")

user32 = ctypes.windll.user32


@dataclass(slots=True)
class WindowInfo:
    """Popis okna ve Windows."""

    hwnd: int
    title: str
    process: str
    visible: bool
    minimized: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "process": self.process,
            "visible": self.visible,
            "minimized": self.minimized,
        }


class WindowManager:
    """Vyhledávání, zaměřování a minimalizace oken."""

    @staticmethod
    def list_windows(visible_only: bool = True) -> list[WindowInfo]:
        """Vrací seznam oken."""
        windows: list[WindowInfo] = []

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindow(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if not title.strip():
                return True
            visible = bool(user32.IsWindowVisible(hwnd))
            if visible_only and not visible:
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process = ""
            try:
                import psutil

                process = psutil.Process(pid.value).name()
            except Exception:  # noqa: BLE001 - proces může být již ukončen
                process = ""
            windows.append(
                WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    process=process,
                    visible=visible,
                    minimized=bool(user32.IsIconic(hwnd)),
                )
            )
            return True

        user32.EnumWindows(callback, 0)
        return windows

    @staticmethod
    def find_window(query: str) -> WindowInfo | None:
        """Najde okno podle názvu (necitlivě na velikost písmen)."""
        needle = query.strip().lower()
        if not needle:
            return None
        windows = WindowManager.list_windows()
        for window in windows:
            if window.title.lower() == needle:
                return window
        for window in windows:
            if needle in window.title.lower():
                return window
        return None

    @staticmethod
    def focus(hwnd: int) -> bool:
        """Přinese okno do popředí a obnoví z minimalizace."""
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Zaměření okna selhalo: %s", exc)
            return False

    @staticmethod
    def minimize(hwnd: int) -> bool:
        try:
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def close(hwnd: int) -> bool:
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return True
        except Exception:  # noqa: BLE001
            return False


class VolumeController:
    """Ovládání hlasitosti zvuku systému.

    Používá pycaw, pokud je dostupný; jinak fallback na klávesové
    zkratky. Hlasitost se mění po 2% krocích.
    """

    _KEY_VOLUME_UP = 0xAF
    _KEY_VOLUME_DOWN = 0xAE
    _KEY_VOLUME_MUTE = 0xAD

    def __init__(self) -> None:
        self._backend: Any | None = None
        self._available = False
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, 0, None)
            self._backend = interface
            self._available = True
            log.info("Ovládání hlasitosti: pycaw")
        except Exception as exc:  # noqa: BLE001
            log.info(
                "Ovládání hlasitosti: pycaw nedostupné (%s), používám zálohu", exc
            )
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def get_volume(self) -> int | None:
        """Aktuální hlasitost v procentech."""
        if self._backend is not None:
            try:
                level = self._backend.GetMasterVolumeLevelScalar()
                return int(round(level * 100))
            except Exception:  # noqa: BLE001
                return None
        return None

    def set_volume(self, percent: int) -> bool:
        """Nastaví hlasitost na 0-100 %."""
        percent = max(0, min(100, int(percent)))
        if self._backend is not None:
            try:
                self._backend.SetMasterVolumeLevelScalar(percent / 100.0, None)
                return True
            except Exception as exc:  # noqa: BLE001
                log.warning("Nastavení hlasitosti selhalo: %s", exc)
                return False
        return self._set_volume_fallback(percent)

    def _set_volume_fallback(self, percent: int) -> bool:
        """Fallback přes klávesové zkratky (odpovídá 2% kroku)."""
        try:
            current = self.get_volume()
            if current is None:
                return False
            delta = int(round(percent / 2)) - int(round(current / 2))
            key = self._KEY_VOLUME_UP if delta > 0 else self._KEY_VOLUME_DOWN
            for _ in range(min(abs(delta), 50)):
                user32.keybd_event(key, 0, 0, 0)
                user32.keybd_event(key, 0, 2, 0)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Záložní nastavení hlasitosti selhalo: %s", exc)
            return False

    def adjust(self, delta: int) -> int | None:
        """Změní hlasitost o delta procent."""
        current = self.get_volume()
        if current is None:
            return None
        target = max(0, min(100, current + int(delta)))
        if self.set_volume(target):
            return target
        return None

    def mute(self, muted: bool = True) -> bool:
        """Ztlumí nebo odtlumí zvuk."""
        try:
            user32.keybd_event(self._KEY_VOLUME_MUTE, 0, 0, 0)
            user32.keybd_event(self._KEY_VOLUME_MUTE, 0, 2, 0)
            return True
        except Exception:  # noqa: BLE001
            return False