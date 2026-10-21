"""Hlavní okno aplikace Martin."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from martin.ui.theme import Theme, get_theme
from martin.ui.widgets.chat_view import ChatView
from martin.ui.widgets.status_bar import StatusBar
from martin.ui.widgets.monitor_panel import MonitorPanel
from martin.ui.pages.settings_page import SettingsPage
from martin.ui.pages.memory_page import MemoryPage
from martin.ui.pages.security_page import SecurityPage
from martin.ui.pages.history_page import HistoryPage
from martin.ui.floating import FloatingWindow

PAGE_TITLES = ("Chat", "Historie", "Paměť", "Bezpečnost", "Nastavení")


class MainWindow(QMainWindow):
    """Hlavní okno Martina - chat, systémová tray, stránky nastavení."""

    toggle_floating = Signal()
    quick_ask = Signal(str)
    request_confirm = Signal(str, dict)

    def __init__(self, app_context: Any) -> None:
        super().__init__()
        self._ctx = app_context
        self._theme: Theme = get_theme(app_context.settings.theme)
        self._floating: FloatingWindow | None = None
        self._quitting = False

        self.setWindowTitle("Martin 2.1 Cloud Edition")
        self.setMinimumSize(1040, 660)
        self.resize(1320, 840)
        self.setWindowIcon(app_context.app_icon())

        self._build_ui()
        self._build_tray()
        self._build_shortcuts()
        self._connect_signals()
        self._ctx.model_changed.emit(self._ctx.current_model_label())
        self._ctx._emit_tts_status()
        definition = self._ctx.hardware.definition
        self._ctx.profile_changed.emit(definition.name, definition.description)

    # -- sestavení UI ---------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Stránky se vytvoří dřív, než je na ně odkazuje hlavička.
        self._chat = ChatView(self._ctx)
        self._history_page = HistoryPage(self._ctx)
        self._memory_page = MemoryPage(self._ctx)
        self._security_page = SecurityPage(self._ctx)
        self._settings_page = SettingsPage(self._ctx)
        self._page_widgets = (
            self._chat,
            self._history_page,
            self._memory_page,
            self._security_page,
            self._settings_page,
        )

        layout.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        # Levá část: přepínatelné stránky.
        self._pages = QStackedWidget()
        for widget in self._page_widgets:
            self._pages.addWidget(widget)
        splitter.addWidget(self._pages)

        self._panel = MonitorPanel(self._ctx)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(self._panel)
        panel_scroll.setMinimumWidth(325)
        splitter.addWidget(panel_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 400])
        layout.addWidget(splitter, 1)

        self._status = StatusBar(self._ctx)
        layout.addWidget(self._status)

        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 8, 14, 8)
        layout.setSpacing(14)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Martin")
        title.setObjectName("Title")
        subtitle = QLabel("Osobní AI asistent")
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)

        layout.addStretch(1)

        self._model_label = QLabel("—")
        self._model_label.setObjectName("Subtitle")
        layout.addWidget(self._model_label)

        # Navigace - samostatný QTabBar, obsah je v QStackedWidget.
        self._tabs = QTabBar()
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        for title_text in PAGE_TITLES:
            self._tabs.addTab(title_text)
        self._tabs.setFixedWidth(400)
        self._tabs.setMinimumHeight(30)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)
        return header

    def _on_tab_changed(self, index: int) -> None:
        """Přepne obsah hlavní části podle aktivní karty."""
        if not (0 <= index < len(self._page_widgets)):
            return
        if index == 1:
            self._history_page.refresh()
        elif index == 3:
            self._security_page.refresh()
        self._pages.setCurrentWidget(self._page_widgets[index])

    def _build_tray(self) -> None:
        from PySide6.QtWidgets import QMenu

        self._tray = QSystemTrayIcon(self._ctx.app_icon(), self)
        self._tray.setToolTip("Martin 2.0")

        menu = QMenu()
        self._tray_show = QAction("Zobrazit Martina", self)
        self._tray_floating = QAction("Plovoucí okno", self)
        self._tray_listen = QAction("Poslouchat (push-to-talk)", self)
        self._tray_stop = QAction("Zastavit mluvení", self)
        self._tray_quit = QAction("Ukončit", self)
        self._tray_floating.setCheckable(True)
        self._tray_floating.setChecked(self._ctx.settings.floating_window)

        self._tray_hide = QAction("Skryt okno", self)
        menu.addAction(self._tray_show)
        self._tray_hide.triggered.connect(self.hide)
        menu.addAction(self._tray_floating)
        menu.addSeparator()
        menu.addAction(self._tray_listen)
        menu.addAction(self._tray_stop)
        menu.addSeparator()
        menu.addAction(self._tray_quit)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray_show.triggered.connect(self._show_window)
        self._tray_floating.triggered.connect(self._toggle_floating)
        self._tray_listen.triggered.connect(self._ctx.toggle_listening)
        self._tray_stop.triggered.connect(self._ctx.stop_generation)
        self._tray_quit.triggered.connect(self._quit_app)
        self._tray.show()

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, activated=self.toggle_floating)
        QShortcut(
            QKeySequence("Ctrl+Shift+Space"),
            self,
            activated=self._ctx.toggle_listening,
        )
        QShortcut(QKeySequence("Ctrl+Shift+L"), self, activated=self._chat.focus_input)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self._ctx.toggle_theme)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self._ctx.stop_generation)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self._quit_app)

    def _connect_signals(self) -> None:
        self._chat.message_submitted.connect(self._ctx.send_message)
        self._chat.stop_requested.connect(self._ctx.stop_generation)
        self._chat.screenshot_requested.connect(self._on_screenshot_requested)
        self._chat.mic_toggled.connect(self._ctx.toggle_listening)
        self._ctx.user_message.connect(lambda text: self._chat.add_message("user", text))
        self.quick_ask.connect(self._ctx.send_message)
        self.toggle_floating.connect(self._toggle_floating)
        self._ctx.model_changed.connect(self._update_model_label)
        self._ctx.status_message.connect(self._status.show_message)
        self._ctx.confirm_requested.connect(self._on_confirm_request)
        self._ctx.theme_changed.connect(self._apply_theme)
        self._ctx.quit_requested.connect(self._quit_app)
        self._update_model_label(self._ctx.current_model_label())

    # -- akce -----------------------------------------------------------
    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_screenshot_requested(self) -> None:
        self._ctx.request_screen_analysis()

    def _toggle_floating(self) -> None:
        if self._floating is None:
            self._floating = FloatingWindow(self._ctx)
            self._floating.quick_ask.connect(self.quick_ask.emit)
        if self._floating.isVisible():
            self._floating.hide()
            self._tray_floating.setChecked(False)
        else:
            self._floating.show()
            self._tray_floating.setChecked(True)
        self._ctx.settings.floating_window = self._floating.isVisible()
        self._ctx.settings_store.save()

    def _on_tray_activated(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_window()

    def _on_confirm_request(self, tool: str, args: dict) -> None:
        from PySide6.QtWidgets import QMessageBox

        detail = ", ".join(f"{k}={v}" for k, v in args.items())
        if tool == "analyze_screen":
            s = self._ctx.settings
            destination = (
                "místní model " + s.local_model
                if s.ai_mode == "Offline"
                else "Ollama Cloud / " + s.vision_model
            )
            detail = (
                f"Snímek okna: {s.screenshot_window or '(okno není vybráno)'}\nOdeslat do: {destination}\nPovoluješ pouze tento jeden snímek.\n"
                + detail
            )
        box = QMessageBox(self)
        box.setWindowTitle("Potvrzení akce")
        box.setText("Martin chce provést následující akci:")
        box.setInformativeText(f"Nástroj: {tool}\n{detail}")
        box.setIcon(QMessageBox.Icon.Question)
        approve = box.addButton("Povolit", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Zamítnout", QMessageBox.ButtonRole.RejectRole)

        def close_when_done(_info):
            box.reject()

        self._ctx.stream_finished.connect(close_when_done)
        box.exec()
        self._ctx.stream_finished.disconnect(close_when_done)
        self._ctx.respond_confirm(box.clickedButton() is approve)

    def _update_model_label(self, label: str) -> None:
        self._model_label.setText(label)

    def _apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        app = QApplication.instance()
        if app is not None:
            from martin.ui.theme import apply_theme

            apply_theme(app, theme)
        self._chat.refresh_theme()
        self._panel.refresh_theme()
        self._status.refresh_theme()
        self._settings_page.refresh_theme()
        self._memory_page.refresh_theme()
        self._security_page.refresh_theme()
        self._history_page.refresh_theme()
        if self._floating is not None:
            self._floating.refresh_theme()

    def _quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.setEnabled(False)
        self._ctx.status_message.emit("Ukončuji hlas a připojení...")
        self._ctx.shutdown_finished.connect(self._finish_quit)
        import threading

        def cleanup():
            try:
                self._ctx.shutdown()
            finally:
                self._ctx.shutdown_finished.emit()

        threading.Thread(target=cleanup, name="martin-shutdown", daemon=True).start()

    def _finish_quit(self) -> None:
        if self._ctx._chat_jobs:
            QTimer.singleShot(100, self._finish_quit)
            return
        self._tray.hide()
        if self._floating is not None:
            self._floating.close()
        QApplication.instance().quit()

    # -- přehrání událostí ----------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._ctx.settings.start_minimized or self._tray.isVisible():
            event.ignore()
            self.hide()
            return
        self._quit_app()
        event.accept()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(1320, 840)
