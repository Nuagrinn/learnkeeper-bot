# Worklog: shared whisper.cpp on VPS

Date: 2026-07-24

## What changed

- Updated VPS STT paths to use a shared assistant directory:
  - `/opt/assistant-shared/whisper.cpp/bin/whisper-cli`;
  - `/opt/assistant-shared/whisper.cpp/models/ggml-medium.bin`.
- Updated `scripts/vps-bootstrap.sh` so bootstrap builds/downloads
  `whisper.cpp` into that shared directory by default.
- Kept `WHISPER_CPP_DIR` override support for custom deployments.
- Documented that multiple assistant bots should reference the same
  `whisper.cpp` binary and model instead of keeping separate model copies.

## Reason

The reminder bot and LearnKeeper both use local `whisper.cpp` STT through
`assistant-toolkit`. The medium model is large, so VPS deployments should store
it once and share it between bot services.
