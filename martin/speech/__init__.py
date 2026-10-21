"""Hlasová vrstva - rozpoznávání řeči (STT) a syntéza (TTS)."""

from martin.speech.tts import PiperTTS, TTSResult
from martin.speech.stt import WhisperSTT, TranscriptionResult

__all__ = ["PiperTTS", "TTSResult", "WhisperSTT", "TranscriptionResult"]