"""Vizuální styl Martina - temný a světlý motiv, animace, animované widgety."""

from martin.ui.theme import Theme, DARK_THEME, LIGHT_THEME, apply_theme, THEMES
from martin.ui.animated import (
    AnimatedButton,
    AnimatedToggle,
    PulseIndicator,
    TypewriterLabel,
    FadeInWidget,
    animated_value,
)

__all__ = [
    "Theme",
    "DARK_THEME",
    "LIGHT_THEME",
    "THEMES",
    "apply_theme",
    "AnimatedButton",
    "AnimatedToggle",
    "PulseIndicator",
    "TypewriterLabel",
    "FadeInWidget",
    "animated_value",
]