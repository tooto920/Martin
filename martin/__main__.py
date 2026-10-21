"""Vstupní bod aplikace Martin 2.0."""

from __future__ import annotations

import sys

from martin.core.logging import setup_logging
from martin.paths import ensure_dirs


def main() -> int:
    """Spustí aplikaci. Vrací exit kód."""
    ensure_dirs()
    setup_logging()
    if len(sys.argv) == 4 and sys.argv[1] == "--stt-worker":
        from martin.speech.worker import worker_main
        return worker_main(sys.argv[2], sys.argv[3])
    if len(sys.argv) >= 3 and sys.argv[1] == "--diagnose-voice":
        from martin.diagnostics import run_diagnostics
        return run_diagnostics(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 12)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import qInstallMessageHandler
    from martin.core.logging import get_logger
    qInstallMessageHandler(lambda kind, context, message: get_logger("martin.qt").warning("%s", message))

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Martin")
    app.setOrganizationName("Martin")
    app.setApplicationVersion("2.0.0")
    app.setQuitOnLastWindowClosed(False)

    from martin.app_context import AppContext
    from martin.ui.main_window import MainWindow
    from martin.ui.theme import apply_theme, get_theme

    context = AppContext()
    apply_theme(app, get_theme(context.settings.theme))

    window = MainWindow(context)
    context.start()

    if context.settings.start_minimized:
        window.hide()
    else:
        window.show()

    if context.settings.floating_window:
        window._toggle_floating()

    app.aboutToQuit.connect(context.shutdown)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
