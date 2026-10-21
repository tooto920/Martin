"""Logování do souboru i konzole."""

from __future__ import annotations

import logging
import logging.handlers
import faulthandler
import os
import sys
import threading
from pathlib import Path

from martin.paths import LOG_DIR

_configured = False
_fault_file = None


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

    filename = f"stt-worker-{os.getpid()}.log" if "--stt-worker" in sys.argv else "martin.log"
    file_handler = logging.handlers.RotatingFileHandler(
        target / filename, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Windowed PyInstaller/pythonw have no stderr. Keep native crash traces
    # in an open, unbuffered file for the entire process lifetime.
    global _fault_file
    _fault_file = open(target / f"fault-{os.getpid()}.log", "ab", buffering=0)
    faulthandler.enable(file=_fault_file, all_threads=True)
    if os.environ.get("MARTIN_TRACE_HANGS") == "1":
        faulthandler.dump_traceback_later(15, repeat=True, file=_fault_file)
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)
    sys.excepthook = lambda kind, value, tb: root.critical(
        "Nezachycená výjimka", exc_info=(kind, value, tb)
    )
    threading.excepthook = lambda args: root.critical(
        "Nezachycená výjimka vlákna %s", args.thread.name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
    root.info("Start pid=%s frozen=%s executable=%s", os.getpid(),
              getattr(sys, "frozen", False), sys.executable)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
