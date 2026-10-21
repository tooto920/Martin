"""Test: GUI zustava responsivni - mereni pres QTimer (realny event loop)."""
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from martin.app_context import AppContext
from martin.ui.theme import apply_theme, get_theme

ctx = AppContext()
apply_theme(app, get_theme(ctx.settings.theme))
from martin.ui.main_window import MainWindow

w = MainWindow(ctx)
w.resize(1320, 840)
w.show()

state = {"n": 0, "max_gap": 0.0, "last": time.perf_counter(), "phase": "init"}


def tick():
    now = time.perf_counter()
    gap = now - state["last"]
    state["last"] = now
    if state["n"] > 0 and gap > state["max_gap"]:
        state["max_gap"] = gap
    state["n"] += 1


timer = QTimer()
timer.timeout.connect(tick)
timer.start(10)

results = {}


def phase2():
    state["phase"] = "record"
    state["max_gap"] = 0.0
    state["n"] = 0
    t0 = time.perf_counter()
    ctx.toggle_listening()
    results["activate_ms"] = (time.perf_counter() - t0) * 1000
    results["activate_gap_ms"] = state["max_gap"] * 1000
    QTimer.singleShot(1500, phase3)


def phase3():
    state["max_gap"] = 0.0
    state["n"] = 0
    t0 = time.perf_counter()
    ctx.toggle_listening()
    results["stop_ms"] = (time.perf_counter() - t0) * 1000
    results["stop_gap_ms"] = state["max_gap"] * 1000
    QTimer.singleShot(6000, phase4)


def phase4():
    results["stt_gap_ms"] = state["max_gap"] * 1000
    results["stt_ticks"] = state["n"]
    results["status"] = ctx.status_message.__class__ and "ok"
    print("=== VYSLEDKY ===", flush=True)
    for k, v in results.items():
        print(f"  {k}: {v}", flush=True)
    ctx.shutdown()
    app.quit()


QTimer.singleShot(300, phase2)
app.exec()
print("HOTOVO", flush=True)