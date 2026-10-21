"""Real Win32/Qt integration against a window owned by this test process."""
import uuid

from PySide6.QtWidgets import QApplication, QWidget

from martin.system.windows import WindowManager
from martin.vision.capture import ScreenCapture


def test_own_qt_window_can_be_found_and_captured():
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    title = "Martin integration " + uuid.uuid4().hex
    widget.setWindowTitle(title)
    widget.resize(240, 120)
    widget.show()
    app.processEvents()
    try:
        window = WindowManager.find_window(title)
        assert window is not None
        assert window.hwnd == int(widget.winId())
        data, meta = ScreenCapture().capture_window(title)
        assert meta["ok"], meta
        assert data.startswith(b"\x89PNG")
        assert meta["width"] >= 240 and meta["height"] >= 120
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
