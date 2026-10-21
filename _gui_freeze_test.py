"""Test: zda GUI zustava responsivni behem rozpoznavani reci."""
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

# Měříme odezvu GUI: kolikrát za sekundu se zpracuje událost.
ticks = {"n": 0, "max_gap": 0.0, "last": time.perf_counter()}


def tick():
    now = time.perf_counter()
    gap = now - ticks["last"]
    ticks["last"] = now
    if ticks["n"] > 0 and gap > ticks["max_gap"]:
        ticks["max_gap"] = gap
    ticks["n"] += 1


timer = QTimer()
timer.timeout.connect(tick)
timer.start(10)  # 100 Hz

print("=== TEST 1: aktivace mikrofonu (blocking?) ===", flush=True)
t0 = time.perf_counter()
ctx.toggle_listening()
activate_ms = (time.perf_counter() - t0) * 1000
print(f"  toggle_listening vrátil za {activate_ms:.1f} ms", flush=True)
print(f"  max UI gap: {ticks['max_gap'] * 1000:.1f} ms", flush=True)
ticks["max_gap"] = 0.0
ticks["n"] = 0

# Nechte nahravat 1.5 s
time.sleep(1.5)
print(f"  během nahrávání max UI gap: {ticks['max_gap'] * 1000:.1f} ms", flush=True)
ticks["max_gap"] = 0.0
ticks["n"] = 0

print()
print("=== TEST 2: zastaveni + rozpoznavani (blocking?) ===", flush=True)
t0 = time.perf_counter()
ctx.toggle_listening()
stop_ms = (time.perf_counter() - t0) * 1000
print(f"  toggle_listening (stop) vrátil za {stop_ms:.1f} ms", flush=True)
print(f"  max UI gap: {ticks['max_gap'] * 1000:.1f} ms", flush=True)

# Nechte worker dobehnout
time.sleep(6)
print(f"  po rozpoznavani max UI gap: {ticks['max_gap'] * 1000:.1f} ms", flush=True)
print(f"  celkem ticku: {ticks['n']}", flush=True)
print()
print("  STATUS:", ctx.status_message, flush=True)
ctx.shutdown()
print("HOTOVO", flush=True)