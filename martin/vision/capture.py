"""Pořizování snímků obrazovky na vyžádání.

Podmínky:
  * Snímek se pořídí POUZE na explicitní požadavek uživatele.
  * Podporuje více monitorů.
  * Snímek se ukládá dočasně a je po analýze smazán.
"""

from __future__ import annotations

import base64
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass(slots=True)
class CaptureTarget:
    """Cíl snímání."""

    monitor_index: int = 0
    window_title: str = ""
    full_screen: bool = True

    def describe(self) -> str:
        if self.window_title:
            return f"okno '{self.window_title}'"
        if self.full_screen:
            return f"monitor {self.monitor_index}"
        return f"oblast na monitoru {self.monitor_index}"


def list_monitors() -> list[dict[str, Any]]:
    """Vypíše dostupné monitory."""
    try:
        import mss  # type: ignore

        with mss.mss() as sct:
            return [
                {
                    "index": i,
                    "width": m["width"],
                    "height": m["height"],
                    "left": m["left"],
                    "top": m["top"],
                    "primary": i == 0,
                }
                for i, m in enumerate(sct.monitors)
            ]
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


class ScreenCapture:
    """Pořizuje snímky obrazovky."""

    def __init__(self, max_dimension: int = 1400) -> None:
        self._max_dimension = max_dimension

    def capture_screen(
        self, monitor_index: int = 0
    ) -> tuple[bytes | None, dict[str, Any]]:
        """Pořídí snímek celého monitoru. Vrací (PNG bytes, metadata)."""
        try:
            import mss  # type: ignore
        except ImportError as exc:
            return None, {"ok": False, "error": f"Knihovna mss není dostupná: {exc}"}

        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                if monitor_index < 0 or monitor_index >= len(monitors):
                    return None, {
                        "ok": False,
                        "error": (
                            f"Monitor {monitor_index} neexistuje. "
                            f"Dostupných monitorů: {len(monitors) - 1}."
                        ),
                    }
                region = monitors[monitor_index]
                raw = sct.grab(region)
                image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception as exc:  # noqa: BLE001
            return None, {"ok": False, "error": f"Snímek se nezdařil: {exc}"}

        image = self._resize(image)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), {
            "ok": True,
            "width": image.width,
            "height": image.height,
            "monitor": monitor_index,
        }

    def capture_window(self, title: str) -> tuple[bytes | None, dict[str, Any]]:
        """Pořídí snímek konkrétního okna (přes Win32 PrintWindow)."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        hwnd = self._find_window(title)
        if not hwnd:
            return None, {"ok": False, "error": f"Okno '{title}' nebylo nalezeno."}

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None, {"ok": False, "error": "Rozměry okna se nepodařilo zjistit."}
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None, {"ok": False, "error": "Okno má neplatné rozměry."}

        window_dc = user32.GetWindowDC(hwnd)
        if not window_dc:
            return None, {"ok": False, "error": "DC okna se nepodařilo získat."}
        mem_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        gdi32.SelectObject(mem_dc, bitmap)
        try:
            user32.PrintWindow(hwnd, mem_dc, 2)
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            header = BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            header.biWidth = width
            header.biHeight = -height
            header.biPlanes = 1
            header.biBitCount = 32
            header.biCompression = 0
            buffer = ctypes.create_string_buffer(width * height * 4)
            gdi32.GetDIBits(
                mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0
            )
            image = Image.frombuffer(
                "RGBA", (width, height), buffer, "raw", "BGRA", 0, 1
            ).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            return None, {"ok": False, "error": f"Snímek okna selhal: {exc}"}
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, window_dc)

        image = self._resize(image)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), {
            "ok": True,
            "width": image.width,
            "height": image.height,
            "window": title,
        }

    def capture_to_temp_file(self, target: CaptureTarget) -> tuple[Path | None, dict[str, Any]]:
        """Pořídí snímek a uloží ho do dočasného souboru."""
        if target.window_title:
            data, meta = self.capture_window(target.window_title)
        else:
            data, meta = self.capture_screen(target.monitor_index)
        if data is None:
            return None, meta
        handle, temp_path = tempfile.mkstemp(prefix="martin_shot_", suffix=".png")
        try:
            with open(handle, "wb") as file:
                file.write(data)
        except OSError as exc:
            return None, {"ok": False, "error": f"Dočasný soubor se nepodařilo vytvořit: {exc}"}
        return Path(temp_path), meta

    def _resize(self, image: Image.Image) -> Image.Image:
        """Zmenší snímek, aby se do promptu vešel rozumný počet tokenů."""
        longest = max(image.width, image.height)
        if longest <= self._max_dimension:
            return image
        ratio = self._max_dimension / longest
        return image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.LANCZOS,
        )

    @staticmethod
    def _find_window(title: str) -> int:
        import ctypes

        user32 = ctypes.windll.user32
        needle = title.strip().lower()
        found: list[int] = []

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if needle in buffer.value.lower():
                found.append(hwnd)
            return True

        user32.EnumWindows(callback, 0)
        return found[0] if found else 0

    @staticmethod
    def to_base64(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")