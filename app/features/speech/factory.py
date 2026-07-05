from __future__ import annotations

from app.config import Settings
from app.features.speech.service import (
    DisabledSpeechToText,
    OpenAISpeechToText,
    SpeechToText,
    WhisperCliSpeechToText,
    WhisperCppSpeechToText,
)


def build_speech_to_text(settings: Settings) -> SpeechToText:
    if settings.stt_provider in ("", "disabled", "none", "off"):
        return DisabledSpeechToText()
    if settings.stt_provider == "openai":
        return OpenAISpeechToText(
            api_key=settings.openai_api_key,
            model=settings.stt_openai_model,
            language=settings.stt_language,
            prompt=settings.stt_prompt,
            timeout_seconds=settings.stt_timeout_seconds,
            ffmpeg_bin=settings.ffmpeg_bin,
        )
    if settings.stt_provider == "whisper_cli":
        return WhisperCliSpeechToText(
            whisper_bin=settings.stt_whisper_bin,
            model=settings.stt_whisper_model,
            language=settings.stt_language,
            timeout_seconds=settings.stt_timeout_seconds,
        )
    if settings.stt_provider == "whisper_cpp":
        return WhisperCppSpeechToText(
            whisper_bin=settings.stt_whisper_cpp_bin,
            model_path=settings.stt_whisper_cpp_model,
            language=settings.stt_language,
            timeout_seconds=settings.stt_timeout_seconds,
            ffmpeg_bin=settings.ffmpeg_bin,
        )
    raise RuntimeError(f"Unsupported STT_PROVIDER: {settings.stt_provider}")
