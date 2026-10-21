"""Barevné motivy aplikace."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class Theme:
    """Barevný motiv s názvy rolí místo hex kódů."""

    name: str
    bg: str
    bg_alt: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_dim: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    warning: str
    danger: str
    user_bubble: str
    assistant_bubble: str
    input_bg: str
    scroll: str
    shadows: str = "rgba(0, 0, 0, 160)"
    extra: dict[str, str] = field(default_factory=dict)

    def color(self, role: str, fallback: str = "#888888") -> QColor:
        """Vrátí QColor pro danou roli."""
        value = getattr(self, role, None) or self.extra.get(role) or fallback
        return QColor(value)


DARK_THEME = Theme(
    name="dark",
    bg="#0e1116",
    bg_alt="#131820",
    surface="#1a2029",
    surface_alt="#222b36",
    border="#2c3644",
    text="#e6edf3",
    text_dim="#b8c4d1",
    text_muted="#7d8b9c",
    accent="#4c8dff",
    accent_hover="#6ba1ff",
    accent_text="#ffffff",
    success="#3fb950",
    warning="#d29922",
    danger="#f85149",
    user_bubble="#1f3a5f",
    assistant_bubble="#1a2029",
    input_bg="#151b23",
    scroll="#2c3644",
    shadows="rgba(0, 0, 0, 180)",
)

LIGHT_THEME = Theme(
    name="light",
    bg="#f4f6fa",
    bg_alt="#eceff5",
    surface="#ffffff",
    surface_alt="#f0f3f8",
    border="#d8dee8",
    text="#16202c",
    text_dim="#3d4a5c",
    text_muted="#6b7889",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_text="#ffffff",
    success="#15803d",
    warning="#b45309",
    danger="#dc2626",
    user_bubble="#dbeafe",
    assistant_bubble="#ffffff",
    input_bg="#ffffff",
    scroll="#c8d0dc",
    shadows="rgba(15, 23, 42, 60)",
)

THEMES = {"dark": DARK_THEME, "light": LIGHT_THEME}


def get_theme(name: str) -> Theme:
    """Vrátí motiv podle názvu (fallback na tmavý)."""
    return THEMES.get(name.lower(), DARK_THEME)


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Aplikuje motiv na celou aplikaci."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.bg))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.input_bg))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.surface_alt))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.accent_text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.text_muted))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(theme))


def build_stylesheet(theme: Theme) -> str:
    """Sestaví QSS stylesheet pro motiv."""
    return f"""
    QWidget {{
        background-color: {theme.bg};
        color: {theme.text};
        font-size: 10pt;
    }}
    QToolTip {{
        background-color: {theme.surface_alt};
        color: {theme.text};
        border: 1px solid {theme.border};
        padding: 4px;
    }}
    QPushButton {{
        background-color: {theme.surface_alt};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{
        background-color: {theme.surface};
        border-color: {theme.accent};
    }}
    QPushButton:pressed {{
        background-color: {theme.bg_alt};
    }}
    QPushButton:disabled {{
        color: {theme.text_muted};
        border-color: {theme.border};
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {theme.input_bg};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 6px 10px;
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 18px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {theme.surface};
        color: {theme.text};
        border: 1px solid {theme.border};
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {theme.scroll};
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {theme.accent};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
    }}
    QScrollBar::handle:horizontal {{
        background: {theme.scroll};
        border-radius: 5px;
        min-width: 28px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QListWidget, QTreeWidget, QTableWidget {{
        background-color: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 8px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background-color: {theme.accent};
        color: {theme.accent_text};
    }}
    QListWidget::item:hover {{
        background-color: {theme.surface_alt};
    }}
    QTabWidget::pane {{
        border: 1px solid {theme.border};
        border-radius: 8px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {theme.text_dim};
        padding: 8px 16px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {theme.text};
        border-bottom: 2px solid {theme.accent};
    }}
    QTabBar::tab:hover {{
        color: {theme.text};
    }}
    QGroupBox {{
        border: 1px solid {theme.border};
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {theme.text_dim};
    }}
    QSlider::groove:horizontal {{
        height: 5px;
        background: {theme.surface_alt};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {theme.accent};
        width: 15px;
        margin: -6px 0;
        border-radius: 7px;
    }}
    QSlider::sub-page:horizontal {{
        background: {theme.accent};
        border-radius: 2px;
    }}
    QProgressBar {{
        background: {theme.surface_alt};
        border: none;
        border-radius: 4px;
        height: 8px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {theme.accent};
        border-radius: 4px;
    }}
    QCheckBox, QRadioButton {{
        spacing: 8px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
    }}
    QCheckBox::indicator {{
        border: 1px solid {theme.border};
        border-radius: 4px;
        background: {theme.input_bg};
    }}
    QCheckBox::indicator:checked {{
        background: {theme.accent};
        border-color: {theme.accent};
    }}
    QMenu {{
        background-color: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 24px 7px 12px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background-color: {theme.accent};
        color: {theme.accent_text};
    }}
    QStatusBar {{
        background: {theme.bg_alt};
        color: {theme.text_dim};
        border-top: 1px solid {theme.border};
    }}
    QHeaderView::section {{
        background: {theme.surface_alt};
        color: {theme.text_dim};
        padding: 6px;
        border: none;
        border-bottom: 1px solid {theme.border};
    }}
    QLabel#Title {{
        font-size: 15pt;
        font-weight: 700;
        color: {theme.text};
    }}
    QLabel#Subtitle {{
        font-size: 9pt;
        color: {theme.text_muted};
    }}
    QLabel#StatValue {{
        font-size: 13pt;
        font-weight: 700;
        color: {theme.text};
    }}
    QLabel#StatLabel {{
        font-size: 8pt;
        color: {theme.text_muted};
    }}
    """