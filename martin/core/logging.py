"""Logování do souboru i konzole."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from martin.paths import LOG_DIR

_configured = False


def setup_logging(level: int = logging.INFO, log_dir: Path | None = None) -> None:
    """Nastaví logování do souboru a stderr (jednou)."""
    global _configured
    if _configured:
        return
    target = Path(log_dir or LOG_DIR)
    target.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        target / "martin.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)