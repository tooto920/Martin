"""Explicit live cloud/Qt/resource diagnostics; only fixed test messages leave PC."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import psutil
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from martin.app_context import AppContext
from martin.system.stats import collect_stats


def run_cloud_diagnostics(report_path):
    app = QApplication.instance() or QApplication([])
    ctx = AppContext()
    ctx.settings.ai_mode = "Cloud"
    ctx.settings.speak_replies = False
    result = {"checks": {}, "requests": [], "samples": [], "errors": [], "replies": []}
    process = psutil.Process()
    done = threading.Event()
    current = []
    beats = []
    deadline = time.monotonic() + 150
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    class Bridge(QObject):
        send = Signal(str)
        stop = Signal()
        quit = Signal()

    bridge = Bridge()
    bridge.send.connect(ctx.send_message)
    bridge.stop.connect(ctx.stop_generation)
    bridge.quit.connect(app.quit)
    ctx.stream_chunk.connect(current.append)

    def finished(info):
        result["replies"].append({"text": "".join(current), "state": info})
        current.clear()
        done.set()

    ctx.stream_finished.connect(finished)
    ctx.error_occurred.connect(result["errors"].append)
    ctx.request_diagnostics.connect(result["requests"].append)
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    ctx.start()

    def save():
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")

    def check(name, ok, **details):
        result["checks"][name] = {"ok": bool(ok), **details}
        save()
        if not ok:
            raise RuntimeError("Kontrola selhala: " + name)

    def resources(label):
        tree = [process] + process.children(recursive=True)
        rss = cpu = 0
        for p in tree:
            try:
                rss += p.memory_info().rss
                times = p.cpu_times()
                cpu += times.user + times.system
            except psutil.Error:
                pass
        result["samples"].append(
            {
                "phase": label,
                "time": time.monotonic(),
                "rss_mb": rss / 1048576,
                "cpu_seconds": cpu,
                "threads": process.num_threads(),
                "children": len(tree) - 1,
            }
        )

    def ask(text, timeout=35):
        done.clear()
        bridge.send.emit(text)
        check("reply_" + str(len(result["replies"])), done.wait(timeout))
        check("ready_" + str(len(result["replies"])), not ctx._busy.is_set())
        resources("after_chat_" + str(len(result["replies"])))

    def run():
        try:
            before = httpx.get(ctx.settings.ollama_url + "/api/ps", timeout=5).json()
            result["ollama_before"] = before
            result["system_before"] = collect_stats().to_dict()
            check("lazy_start", ctx.stt_backend._process is None and ctx.tts._voice_obj is None)
            resources("idle_start")
            time.sleep(15)
            resources("idle_after_15s")
            ask("Ahoj. Odpověz krátce česky.")
            for text in (
                "Kolik je dva plus dva? Jedna věta.",
                "Kontrolní slova v tomto rozhovoru jsou MODRY MOST. Odpověz OK.",
                "Jaká dvě kontrolní slova jsem právě uvedl?",
                "Vysvětli jednou větou, co je grafická karta.",
            ):
                ask(text)
            check(
                "history_context",
                "modr" in result["replies"][-2]["text"].lower()
                and "most" in result["replies"][-2]["text"].lower(),
            )
            # Cancellation while generation is active; no replay is issued.
            done.clear()
            bridge.send.emit(
                "Vypiš čísla od jedné do tisíce, každé na samostatném řádku, bez úvodu a bez zkrácení."
            )
            time.sleep(0.35)
            t = time.perf_counter()
            bridge.stop.emit()
            check("stop_returns_ready", done.wait(5), seconds=time.perf_counter() - t)
            check("stop_state", result["replies"][-1]["state"] == "Zrušeno")
            ask("Napiš jediné slovo: funguje.")
            result["ollama_after"] = httpx.get(
                ctx.settings.ollama_url + "/api/ps", timeout=5
            ).json()
            result["system_after"] = collect_stats().to_dict()
            check(
                "only_cloud_requests",
                all(r["model"] == ctx.settings.cloud_model for r in result["requests"]),
            )
            before_names = {m["name"] for m in before.get("models", [])}
            after_names = {m["name"] for m in result["ollama_after"].get("models", [])}
            check(
                "no_new_local_model",
                not (after_names - before_names),
                before=sorted(before_names),
                after=sorted(after_names),
            )
            check("no_http_workers_left", not ctx.client._operations)
            result["usage"] = ctx.usage.snapshot()
            check("bounded_worker_count", process.num_threads() < 80)
        except Exception as exc:
            result["errors"].append(str(exc))
        finally:
            ctx.shutdown()
            result["max_qt_gap_s"] = max((b - a for a, b in zip(beats, beats[1:])), default=0)
            result["deadline_remaining_s"] = deadline - time.monotonic()
            save()
            bridge.quit.emit()

    threading.Thread(target=run, name="martin-cloud-diagnostics", daemon=True).start()
    QTimer.singleShot(160000, app.quit)
    app.exec()
    return 1 if result["errors"] else 0
