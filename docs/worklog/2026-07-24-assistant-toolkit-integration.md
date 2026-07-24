# Assistant Toolkit Integration

Date: 2026-07-24

## Goal

Start moving reusable infrastructure out of LearnKeeper and into the shared
`assistant-toolkit` package so the upcoming reminder bot can reuse the same STT,
Claude CLI and small helper code without importing LearnKeeper internals.

## What changed

- Added `assistant-toolkit` as a dependency in `requirements.txt`.
- Replaced `app/core/claude_cli.py` with a compatibility wrapper over
  `assistant_toolkit.llm`.
- Replaced `app/features/speech/service.py` with a compatibility wrapper over
  `assistant_toolkit.speech.service`.
- Kept `app/features/speech/factory.py` as the local LearnKeeper factory, but it
  now creates compatibility classes backed by `assistant_toolkit.speech`.
- Updated quiz generator to import Claude tool policy, paid API env names and
  Claude usage parsing from `assistant_toolkit.llm`.
- Updated STT tests to patch the new package boundary.

## What did not move

- LearnKeeper quiz/review/topic domain logic.
- LearnKeeper prompts and JSON schemas.
- Telegram menus, callback data and formatter details that are specific to
  LearnKeeper.
- LLM usage persistence in SQLite.

## Validation

- Installed local editable `assistant-toolkit` into LearnKeeper's `.venv`.
- Ran targeted tests:
  `tests.test_speech tests.test_claude_cli tests.test_quiz_generator tests.test_topic_inbox_agent tests.test_mistake_work_agent tests.test_explain_check_agent`.
- Ran full test suite: `python -m unittest discover -s tests`.
- Result: 130 tests passed.
- Tried `pip install -r requirements.txt`; pip successfully resolved
  `assistant-toolkit` from GitHub at commit `d0362c6`, then failed later while
  building `openai` dependency `jiter` on the local MSYS Python 3.14 environment
  (`Unsupported platform: mingw_x86_64_ucrt_gnu`). This is unrelated to the new
  shared package and should not affect the Linux VPS deploy path.

## Deployment note

`requirements.txt` installs `assistant-toolkit` from GitHub. If the repository is
private, the VPS deploy user needs GitHub credentials or a deploy key that can
read `Nuagrinn/assistant-toolkit`.
