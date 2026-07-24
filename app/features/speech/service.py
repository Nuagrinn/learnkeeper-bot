from __future__ import annotations

from assistant_toolkit.speech.service import (
    OpenAISpeechToText as ToolkitOpenAISpeechToText,
    SpeechToText,
    SpeechToTextError,
    WhisperCliSpeechToText as ToolkitWhisperCliSpeechToText,
    WhisperCppSpeechToText as ToolkitWhisperCppSpeechToText,
)


class DisabledSpeechToText:
    provider = "disabled"
    model = "none"

    def transcribe(self, path):
        raise SpeechToTextError(
            "Распознавание голосовых сообщений пока не настроено. "
            "В `.env` выбери STT_PROVIDER=whisper_cli, STT_PROVIDER=whisper_cpp "
            "или STT_PROVIDER=openai."
        )


class OpenAISpeechToText(ToolkitOpenAISpeechToText):
    pass


class WhisperCliSpeechToText(ToolkitWhisperCliSpeechToText):
    pass


class WhisperCppSpeechToText(ToolkitWhisperCppSpeechToText):
    def transcribe(self, path):
        if not self.model_path.exists():
            raise SpeechToTextError(
                f"Не найдена модель whisper.cpp: {self.model_path}. "
                "Скачай GGML-модель или укажи STT_WHISPER_CPP_MODEL."
            )
        return super().transcribe(path)


__all__ = [
    "DisabledSpeechToText",
    "OpenAISpeechToText",
    "SpeechToText",
    "SpeechToTextError",
    "WhisperCliSpeechToText",
    "WhisperCppSpeechToText",
]
