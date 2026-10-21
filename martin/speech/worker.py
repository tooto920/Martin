"""Fixed, authenticated local STT protocol; native decoder stays outside Qt."""

from __future__ import annotations

import base64
import json
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from martin.core.logging import get_logger, setup_logging
from martin.speech.whispercpp_backend import (
    WhisperCppBackend,
    SttDiagnostics,
    TranscriptionOutcome,
)

log = get_logger(__name__)
MAX_MESSAGE = 16_000_000


def send(sock, value):
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_MESSAGE:
        raise RuntimeError("Zvukový požadavek je příliš velký.")
    sock.sendall(struct.pack("!I", len(data)) + data)


def receive(sock, cancelled=None, timeout=60):
    deadline = time.monotonic() + timeout

    def read(count):
        data = bytearray()
        while len(data) < count:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("Rozpoznání zrušeno.")
            if time.monotonic() > deadline:
                raise RuntimeError("Rozpoznávání řeči překročilo časový limit.")
            try:
                part = sock.recv(count - len(data))
            except socket.timeout:
                continue
            if not part:
                raise RuntimeError(
                    "Proces rozpoznávání řeči se neočekávaně ukončil. Podrobnosti jsou v diagnostickém logu."
                )
            data.extend(part)
        return bytes(data)

    size = struct.unpack("!I", read(4))[0]
    if size > MAX_MESSAGE:
        raise RuntimeError("Neplatná délka zprávy STT.")
    return json.loads(read(size))


class IsolatedWhisperBackend(WhisperCppBackend):
    """Persistent decoder process with cancellation and bounded lifetime."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._process = None
        self._socket = None
        self._request_lock = threading.Lock()

    def _close_worker(self):
        with self._lock:
            sock, self._socket = self._socket, None
            process, self._process = self._process, None
            self._model = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if process:
            # Windows venv python.exe may be a launcher with an interpreter
            # child. Track only this worker's descendants before terminating
            # it; otherwise native inference can survive its launcher.
            import psutil

            try:
                descendants = psutil.Process(process.pid).children(recursive=True)
            except psutil.Error:
                descendants = []
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            for child in reversed(descendants):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs(descendants, timeout=3)
            for child in alive:
                try:
                    child.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(alive, timeout=3)

    def cancel(self):
        self._cancel.set()
        self._close_worker()

    def unload(self):
        self._close_worker()

    def set_model(self, model_size):
        if self._model_size != model_size:
            self.cancel()
            super().set_model(model_size)
            self.reset_cancel()

    def set_language(self, language):
        if self._language != language:
            self.cancel()
            super().set_language(language)
            self.reset_cancel()

    def _connect_worker(self):
        with self._lock:
            if self._socket is not None and self._process.poll() is None:
                return self._socket
        self._close_worker()
        if self._cancel.is_set():
            raise RuntimeError("Rozpoznání zrušeno.")
        if self.model_file() is None or self.vad_file() is None:
            raise RuntimeError(
                "Chybí model Whisper nebo VAD. Zkontroluj složku models vedle Martin.exe."
            )
        token = secrets.token_hex(32)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(0.25)
            args = [sys.executable]
            if not getattr(sys, "frozen", False):
                args += ["-m", "martin.speech.worker"]
            args += ["--stt-worker", str(listener.getsockname()[1]), token]
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                cwd=None
                if getattr(sys, "frozen", False)
                else str(Path(__file__).resolve().parents[2]),
            )
            with self._lock:
                self._process = process
            deadline = time.monotonic() + 15
            while True:
                if (
                    self._cancel.is_set()
                    or process.poll() is not None
                    or time.monotonic() > deadline
                ):
                    code = process.poll()
                    self._close_worker()
                    raise RuntimeError(
                        f"STT proces se nepodařilo spustit (exit={code}). Viz diagnostické logy."
                    )
                try:
                    sock, _ = listener.accept()
                    sock.settimeout(0.25)
                    if not secrets.compare_digest(receive(sock, timeout=2).get("token", ""), token):
                        sock.close()
                        continue
                    break
                except socket.timeout:
                    continue
        with self._lock:
            self._socket = sock
        send(
            sock,
            {
                "op": "init",
                "model_size": self._model_size,
                "models_dir": str(self._models_dir),
                "n_threads": self._n_threads,
                "language": self._language,
                "vad_model_path": str(self._vad_model_path),
                "silence_rms": self._silence_rms,
            },
        )
        result = receive(sock, self._cancel, timeout=45)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Načtení STT selhalo."))
        self._model = True
        log.info("STT worker připraven pid=%s model_load_s=%.3f", process.pid, result["load_s"])
        return sock

    def warm_up(self):
        with self._request_lock:
            try:
                self._connect_worker()
                return True
            except Exception:
                log.exception("Načtení izolovaného STT selhalo")
                self._close_worker()
                return False

    def transcribe(self, audio, sample_rate=16000):
        with self._request_lock:
            try:
                sock = self._connect_worker()
                data = np.ascontiguousarray(audio, dtype="<f4")
                if data.size > 16000 * 60 or not np.all(np.isfinite(data)):
                    raise RuntimeError("Neplatný nebo příliš dlouhý zvukový záznam.")
                send(
                    sock,
                    {
                        "op": "transcribe",
                        "audio": base64.b64encode(data.tobytes()).decode("ascii"),
                        "sample_rate": sample_rate,
                        "silence_rms": self._silence_rms,
                    },
                )
                result = receive(sock, self._cancel, timeout=60)
                return TranscriptionOutcome(
                    result["text"],
                    result["ok"],
                    result["error"],
                    SttDiagnostics(**result["diagnostics"]),
                )
            except Exception as exc:
                log.exception("Izolované STT selhalo")
                self._close_worker()
                return TranscriptionOutcome("", False, str(exc))


def worker_main(port, token):
    setup_logging()
    with socket.create_connection(("127.0.0.1", int(port)), timeout=10) as sock:
        sock.settimeout(0.25)
        send(sock, {"token": token})
        config = receive(sock)
        if config.pop("op") != "init":
            return 2
        backend = WhisperCppBackend(**config)
        start = time.perf_counter()
        ok = backend.warm_up()
        send(
            sock,
            {
                "ok": ok,
                "error": "Nepodařilo se načíst Whisper; viz log.",
                "load_s": time.perf_counter() - start,
            },
        )
        if not ok:
            return 1
        while True:
            try:
                request = receive(sock, timeout=3600)
            except (RuntimeError, OSError):
                return 0
            if request.get("op") != "transcribe":
                return 2
            audio = np.frombuffer(
                base64.b64decode(request["audio"], validate=True), dtype="<f4"
            ).copy()
            if audio.size > 16000 * 60:
                return 2
            backend.set_silence_threshold(request["silence_rms"])
            result = backend.transcribe(audio, sample_rate=int(request["sample_rate"]))
            send(sock, result.to_dict())


if __name__ == "__main__":
    raise SystemExit(worker_main(sys.argv[-2], sys.argv[-1]))
