from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from app.features.speech.service import (
    DisabledSpeechToText,
    SpeechToTextError,
    WhisperCliSpeechToText,
    WhisperCppSpeechToText,
)


class SpeechToTextTest(unittest.TestCase):
    def test_disabled_provider_has_clear_error(self) -> None:
        with self.assertRaises(SpeechToTextError) as ctx:
            DisabledSpeechToText().transcribe(Path("voice.oga"))

        self.assertIn("STT_PROVIDER", str(ctx.exception))

    def test_whisper_cli_reads_txt_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "voice.oga"
            audio.write_bytes(b"fake")

            def fake_run(command, **kwargs):
                output_dir = Path(command[command.index("--output_dir") + 1])
                (output_dir / "voice.txt").write_text("  слайсы\n", encoding="utf-8")
                return CompletedProcess(command, 0, stdout="", stderr="")

            transcriber = WhisperCliSpeechToText(
                whisper_bin="whisper",
                model="tiny",
                run_command=fake_run,
            )

            self.assertEqual("слайсы", transcriber.transcribe(audio))

    def test_whisper_cpp_reads_txt_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "voice.oga"
            model = root / "ggml-base.bin"
            audio.write_bytes(b"fake")
            model.write_bytes(b"model")

            def fake_run(command, **kwargs):
                output_base = Path(command[command.index("-of") + 1])
                output_base.with_suffix(".txt").write_text(" мапы ", encoding="utf-8")
                return CompletedProcess(command, 0, stdout="", stderr="")

            transcriber = WhisperCppSpeechToText(
                whisper_bin="whisper-cli.exe",
                model_path=model,
                run_command=fake_run,
            )

            with patch("app.features.speech.service._convert_to_wav", return_value=audio):
                self.assertEqual("мапы", transcriber.transcribe(audio))

    def test_whisper_cpp_requires_model_file(self) -> None:
        transcriber = WhisperCppSpeechToText(
            whisper_bin="whisper-cli.exe",
            model_path=Path("missing.bin"),
        )

        with self.assertRaises(SpeechToTextError) as ctx:
            transcriber.transcribe(Path("voice.oga"))

        self.assertIn("Не найдена модель", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
