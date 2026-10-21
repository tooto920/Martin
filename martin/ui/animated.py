"""Animované widgety - dávají aplikaci život.

Všechny animace jsou založené na QPropertyAnimation a běží plynule
v hlavní smyčce Qt, takže nikdy neblokují vykreslování.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsOpacityEffect,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class AnimatedButton(QPushButton):
    """Tlačítko s plynulým přechodem barvy při najetí a stisku."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._base_color = QColor("#4c8dff")
        self._hover_color = QColor("#6ba1ff")
        self._pressed_color = QColor("#3a72d8")
        self._current_color = QColor(self._base_color)
        self._animation: QPropertyAnimation | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def set_colors(self, base: str, hover: str, pressed: str) -> None:
        self._base_color = QColor(base)
        self._hover_color = QColor(hover)
        self._pressed_color = QColor(pressed)
        self._current_color = QColor(base)
        self._refresh_style()

    def _refresh_style(self) -> None:
        color = self._current_color.name()
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {color};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 600;
            }}
            QPushButton:disabled {{
                background-color: rgba(120, 130, 145, 90);
                color: rgba(230, 237, 243, 120);
            }}
            """
        )

    def _animate_to(self, color: QColor, duration: int = 140) -> None:
        if self._animation is not None:
            self._animation.stop()
        self._animation = QPropertyAnimation(self, b"current_color", self)
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._current_color)
        self._animation.setEndValue(color)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def update(value: Any) -> None:
            self._current_color = QColor(value)
            self._refresh_style()

        try:
            self._animation.finished.connect(update)
            self._animation.start()
        except (TypeError, RuntimeError):
            self._current_color = color
            self._refresh_style()

    def enterEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self._animate_to(self._hover_color)
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self._animate_to(self._base_color)
        super().leaveEvent(event)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self._animate_to(self._pressed_color, 90)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self._animate_to(self._hover_color, 160)
        super().mouseReleaseEvent(event)

    def get_current_color(self) -> QColor:
        return QColor(self._current_color)

    def set_current_color(self, color: QColor) -> None:
        self._current_color = QColor(color)
        self._refresh_style()

    current_color = property(
        lambda self: self._current_color, set_current_color
    )


class AnimatedToggle(QCheckBox):
    """Přepínač s animovaným přechodem barvy."""

    toggled_animated = Signal(bool)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._on_color = QColor("#4c8dff")
        self._off_color = QColor("#3a4453")
        self._color = QColor(self._off_color)
        self._animation: QPropertyAnimation | None = None
        self.stateChanged.connect(self._on_state_changed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_colors(self, on_color: str, off_color: str) -> None:
        self._on_color = QColor(on_color)
        self._off_color = QColor(off_color)
        self._color = QColor(self._on_color if self.isChecked() else self._off_color)
        self._refresh()

    def _refresh(self) -> None:
        color = self._color.name()
        self.setStyleSheet(
            f"""
            QCheckBox::indicator {{
                width: 38px;
                height: 20px;
                border-radius: 10px;
                background-color: {color};
                border: none;
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {self._on_color.name()};
            }}
            QCheckBox::indicator:checked {{
                background-color: {color};
            }}
            """
        )

    def _on_state_changed(self, checked: bool) -> None:
        target = self._on_color if checked else self._off_color
        if self._animation is not None:
            self._animation.stop()
        self._animation = QPropertyAnimation(self, b"toggle_color", self)
        self._animation.setDuration(180)
        self._animation.setStartValue(self._color)
        self._animation.setEndValue(target)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def update(value: Any) -> None:
            self._color = QColor(value)
            self._refresh()

        try:
            self._animation.finished.connect(update)
            self._animation.start()
        except (TypeError, RuntimeError):
            self._color = QColor(target)
            self._refresh()
        self.toggled_animated.emit(checked)

    def get_toggle_color(self) -> QColor:
        return QColor(self._color)

    def set_toggle_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self._refresh()

    toggle_color = property(lambda self: self._color, set_toggle_color)


class PulseIndicator(QWidget):
    """Kruhový indikátor, který jemně pulzuje - používá se jako
    "Martin mluví" / "poslouchá" indikátor."""

    def __init__(self, color: str = "#4c8dff", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._phase = 0.0
        self._active = False
        self.setFixedSize(18, 18)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def _tick(self) -> None:
        if self._active:
            self._phase = (self._phase + 0.09) % (2 * 3.141592653589793)
            self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        radius = 4.0
        if self._active:
            glow = 6.0 + 2.5 * abs(math.sin(self._phase))
            halo = QColor(self._color)
            halo.setAlpha(70)
            painter.setBrush(halo)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, glow, glow)
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius, radius)
        painter.end()


class TypewriterLabel(QLabel):
    """Popis, který postupně vypisuje text - používá se pro odpovědi."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self._visible_chars = 0
        self._timer = QTimer(self)
        self._timer.setInterval(18)
        self._timer.timeout.connect(self._step)
        self.setText(text)
        self.setWordWrap(True)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text or ""
        self._visible_chars = len(self._full_text)
        super().setText(self._full_text)

    def type_text(self, text: str, interval: int = 18) -> None:
        """Spustí efekt postupného vypisování."""
        self._full_text = text or ""
        self._visible_chars = 0
        super().setText("")
        self._timer.setInterval(interval)
        self._timer.start()

    def _step(self) -> None:
        if self._visible_chars >= len(self._full_text):
            self._timer.stop()
            return
        self._visible_chars += 2
        super().setText(self._full_text[: self._visible_chars])

    def finish(self) -> None:
        """Dokončí vypisování okamžitě."""
        self._timer.stop()
        self._visible_chars = len(self._full_text)
        super().setText(self._full_text)


class FadeInWidget(QWidget):
    """Widget, který se zobrazí s plynulým fade-in."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._animation: QPropertyAnimation | None = None

    def fade_in(self, duration: int = 220) -> None:
        self.show()
        if self._animation is not None:
            self._animation.stop()
        self._effect.setOpacity(0.0)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(duration)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()

    def fade_out(self, duration: int = 180) -> None:
        if self._animation is not None:
            self._animation.stop()
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(self.hide)
        self._animation.start()


def animated_value(
    widget: QLabel,
    from_value: float,
    to_value: float,
    suffix: str = " %",
    duration: int = 500,
    decimals: int = 0,
) -> QPropertyAnimation:
    """Plynule převezme hodnotu v popisku (např. pro CPU usage)."""
    animation = QPropertyAnimation(widget, b"value", widget)
    animation.setDuration(duration)
    animation.setStartValue(from_value)
    animation.setEndValue(to_value)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def update(value: Any) -> None:
        widget.setText(f"{value:.{decimals}f}{suffix}")

    animation.valueChanged.connect(update)
    animation.start()
    return animation