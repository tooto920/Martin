"""Opt-in diagnostics against the real packaged application and local devices.

No captured microphone audio is saved or dispatched to an LLM/tool.
Only the fixed Czech arithmetic prompt is used for the Ollama check.
"""

from __future__ import annotations

import json
import threading
import time
import wave
from pathlib import Path

import numpy as np
import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from martin.app_context import AppContext
from martin.speech.stt import AudioRecorder, resample
from martin.speech.streaming_tts import StreamingTTS
from martin.speech.pipeline import VoiceTimings


def run_diagnostics(report_path: str, cycles: int = 12) -> int:
    app = QApplication.instance() or QApplication([])
    ctx = AppContext()
    ctx.settings.ai_mode = "Cloud"
    ctx.settings.local_only = False
    ctx.settings.allow_cloud_fallback = True
    ctx.settings.speak_replies = False
    report = {
        "checks": {},
        "errors": [],
        "hardware": "real local microphone and speaker; Czech recognition uses synthetic Piper audio",
    }
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(time.perf_counter()))
    timer.start(20)
    ctx.shutdown_finished.connect(app.quit)
    llm_finished = threading.Event()
    ctx.stream_finished.connect(lambda _: llm_finished.set())
    ctx.error_occurred.connect(lambda error: report["errors"].append(error))
    report["requests"] = []
    report["resources"] = []
    try:
        import sounddevice as sd

        report["audio_devices"] = {
            kind: dict(sd.query_devices(kind=kind)) for kind in ("input", "output")
        }
    except Exception as exc:
        report["audio_devices"] = {"error": str(exc)}
    ctx.request_diagnostics.connect(lambda data: report["requests"].append(data))
    ctx.start()

    def save_report():
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(name, condition, **details):
        report["checks"][name] = {"ok": bool(condition), **details}
        save_report()
        if not condition:
            raise RuntimeError(f"Kontrola selhala: {name}")

    def run():
        try:

            def resource(phase):
                proc = psutil.Process()
                rss = cpu = 0
                for item in [proc] + proc.children(recursive=True):
                    try:
                        rss += item.memory_info().rss
                        times = item.cpu_times()
                        cpu += times.user + times.system
                    except psutil.Error:
                        pass
                report["resources"].append(
                    {
                        "phase": phase,
                        "rss_mb": rss / 1048576,
                        "cpu_seconds": cpu,
                        "time": time.perf_counter(),
                    }
                )

            resource("startup")
            check(
                "lazy_startup",
                ctx._warmup_thread is None
                and ctx.stt_backend._process is None
                and ctx.tts._voice_obj is None,
            )
            activation = []
            samples = []
            for _ in range(cycles):
                check("microphone_start", ctx.voice_pipeline.start_recording())
                time.sleep(0.65)
                audio = ctx.voice_pipeline.stop_recording()
                activation.append(ctx.voice_pipeline.timings.mic_activation_s)
                samples.append(0 if audio is None else len(audio))
                check("microphone_release", not ctx.voice_pipeline._record_thread.is_alive())
            check(
                "microphone_capture",
                all(n > 0 for n in samples),
                cycles=cycles,
                samples=samples,
                activation_s=activation,
            )
            for _ in range(cycles * 2):
                ctx.voice_pipeline.start_recording()
                ctx.voice_pipeline.cancel()
                ctx.voice_pipeline.stop_recording()
                check("rapid_cancel_release", not ctx.voice_pipeline._record_thread.is_alive())
            report["checks"]["rapid_cancel_release"]["cycles"] = cycles * 2
            bad = AudioRecorder(-999999)
            try:
                check("invalid_device", not bad.start())
            finally:
                bad.stop()
            ctx.stt_backend.reset_cancel()
            t = time.perf_counter()
            check("stt_worker_load", ctx.stt_backend.warm_up())
            report["checks"]["stt_worker_load"]["seconds"] = time.perf_counter() - t
            resource("stt_loaded")
            silence = ctx.stt_backend.transcribe(np.zeros(16000, dtype=np.float32))
            check("digital_silence", not silence.ok and not silence.text)
            noise = np.random.default_rng(42).normal(0, 0.01, 16000).astype(np.float32)
            noise_result = ctx.stt_backend.transcribe(noise)
            check(
                "synthetic_noise",
                not noise_result.text,
                diagnostics=noise_result.diagnostics.to_dict(),
            )
            tts = ctx.tts.synthesize("Martine, otevři Microsoft Flight Simulator.")
            resource("piper_loaded")
            check(
                "czech_tts",
                tts.ok,
                load_s=tts.load_s,
                synth_s=tts.synth_s,
                audio_duration_s=tts.duration_s,
            )
            audio_path = Path(tts.audio_path)
            with wave.open(str(audio_path)) as wav:
                audio = (
                    np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(
                        np.float32
                    )
                    / 32768
                )
                rate = wav.getframerate()
            outcome = ctx.stt_backend.transcribe(audio, rate)
            check(
                "czech_synthetic_stt",
                outcome.ok
                and "martin" in outcome.text.lower()
                and ("flight" in outcome.text.lower() or "simul" in outcome.text.lower()),
                transcript=outcome.text,
                diagnostics=outcome.diagnostics.to_dict(),
            )
            t = time.perf_counter()
            played = ctx.tts.play_file(str(audio_path))
            check("speaker_playback", played, seconds=time.perf_counter() - t)
            streamer = StreamingTTS(ctx.tts)
            for piece in [
                "**Tohle ",
                "je test hlasového výstupu.** ",
                "Druhá věta se přehraje celá.",
            ]:
                streamer.push_text(piece)
            streamer.finish()
            check(
                "streaming_playback",
                streamer.wait(30) and not streamer.error,
                first_audio_s=streamer.time_to_first_audio,
                played_sentences=streamer._samples_played,
                dropped=streamer.dropped_sentences,
            )
            # Kill only our isolated decoder, then prove that the GUI and a
            # replacement decoder still work. This is failure injection.
            ctx.stt_backend._process.terminate()
            ctx.stt_backend._process.wait(timeout=5)
            recovered = ctx.stt_backend.transcribe(np.zeros(16000, dtype=np.float32))
            check("decoder_process_recovery", not recovered.text and "tich" in recovered.error)
            t = time.perf_counter()
            ctx._transcript_received.emit(
                "Kolik je dva plus dva? Odpověz jednou větou.", ctx._voice_generation
            )
            check("qt_voice_to_chat", llm_finished.wait(60))
            messages = ctx.conversations.get_messages(ctx._conversation_id)
            check(
                "conversation_roles",
                [m["role"] for m in messages] == ["user", "assistant"],
                reply=messages[-1]["content"],
                seconds=time.perf_counter() - t,
                timings=ctx.voice_pipeline.timings.to_dict(),
            )
            greeting = ctx.tts.synthesize("Ahoj Martine, jak se dnes máš?")
            check("voice_e2e_fixture", greeting.ok)
            with wave.open(greeting.audio_path) as wav:
                pcm = (
                    np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(
                        np.float32
                    )
                    / 32768
                )
                rate = wav.getframerate()
            Path(greeting.audio_path).unlink(missing_ok=True)
            ctx.voice_pipeline._cycle_start = time.perf_counter()
            ctx.voice_pipeline._cancelled = False
            ctx.voice_pipeline._timings = VoiceTimings(record_duration_s=len(pcm) / rate)
            transcript = ctx.voice_pipeline.process_recording(resample(pcm, rate, 16000))
            check(
                "voice_e2e_transcript",
                bool(transcript) and "ahoj" in transcript.lower(),
                transcript=transcript,
            )
            ctx.settings.speak_replies = True
            llm_finished.clear()
            ctx._transcript_received.emit(transcript, ctx._voice_generation)
            completed = llm_finished.wait(60)
            check(
                "synthetic_voice_cloud_piper_e2e",
                completed,
                timings=ctx.voice_pipeline.timings.to_dict(),
            )
            resource("after_voice_e2e")
            check(
                "no_empty_voice_reply",
                bool(ctx.conversations.get_messages(ctx._conversation_id)[-1]["content"].strip()),
            )
            ctx.voice_pipeline.start_recording()
            time.sleep(0.03)
        except Exception as exc:
            report["errors"].append(str(exc))
        finally:
            try:
                ctx.shutdown()
                check(
                    "shutdown_audio",
                    ctx.voice_pipeline._record_thread is None
                    or not ctx.voice_pipeline._record_thread.is_alive(),
                )
                check("shutdown_decoder", ctx.stt_backend._process is None)
            except Exception as exc:
                report["errors"].append(f"shutdown: {exc}")
            report["gui_heartbeat_max_gap_s"] = max(
                (b - a for a, b in zip(beats, beats[1:])), default=0
            )
            target = Path(report_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            ctx.shutdown_finished.emit()

    threading.Thread(target=run, name="martin-diagnostics", daemon=True).start()
    app.exec()
    return 1 if report["errors"] else 0
