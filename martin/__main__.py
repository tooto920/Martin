"""Vstupní bod aplikace Martin 2.0."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from martin.core.logging import setup_logging
from martin.paths import ensure_dirs


def main() -> int:
    """Spustí aplikaci. Vrací exit kód."""
    ensure_dirs()
    setup_logging()

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
        from martin.ui.floating import FloatingWindow

        floating = FloatingWindow(context)
        floating.quick_ask.connect(context.send_message)
        floating.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())