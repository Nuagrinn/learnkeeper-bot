# LearnKeeper

Local-first bot for spaced repetition over an `interview-review` repository.

Current stage: local core MVP plus Telegram adapter, Claude CLI generation,
mistake review backlog and a first VPS deployment kit.

## What works now

- SQLite schema bootstrap.
- Local review task creation.
- Due task listing.
- Schedule listing.
- Stage advancement by quiz score.
- Due review notifications with a "Start test" button.
- One-message quiz flow: question -> A/B/C/D answer -> next question -> report.
- Instant quiz flow: choose a block, then a topic, then take a quiz immediately
  without creating a review task. Whole-block quizzes (all topics in a section
  at once) are temporarily disabled — combining a section's materials can
  total hundreds of thousands of chars, which needs proportional/structural
  sampling before it is worth re-enabling; picking it shows a Telegram alert.
- Daily random quiz mode: toggle in Telegram, then get one random ready-topic
  test offer every morning.
- Fake quiz generator for local flow testing.
- Claude CLI quiz generator via subscription OAuth, without Anthropic API key
  fallback when `ALLOW_PAID_API=false`.
- SQL migrations.
- Local `interview-review` topic lookup from `ROOT.md`, optional `topics.json`,
  and markdown files.
- Topic statistics contract: `section`, `order_index`, `material_fingerprint`.
- Topic inbox for new study ideas: Telegram text/voice -> lightweight agent
  normalizes the title/block -> SQLite backlog. `interview-review` is updated
  manually by the user.
- Mistake review backlog: after a quiz with wrong answers, the bot can ask an
  agent for a full report and save it into SQLite for later manual work.
- Optional `git pull --ff-only` before quiz generation, so VPS can refresh
  `interview-review` before reading materials.
- VPS deployment files: systemd unit, bootstrap script, deploy script, SQLite
  backup timer and GitHub Actions workflow template.
- Telegram commands for owner-only `/topics`, `/review_add`, `/topic_add`,
  `/schedule`, `/due`.

## Local Usage

Run commands from this directory:

```powershell
python -m app.cli migrate
python -m app.cli db-status
python -m app.cli repo-status
python -m app.cli topics
python -m app.cli review-add "Python GIL"
python -m app.cli schedule
python -m app.cli due
python -m app.cli complete <task_id> 85
python -m app.cli quiz-preview "слайсы" --questions 5
```

For local development, CLI `review-add` replaces an existing active task for the
same topic: the old task is marked `cancelled`, and a fresh task is created with
the requested `--due-days`. Telegram `/review_add` keeps the safer behavior and
does not create duplicates.

You can point the CLI at your materials repo per command:

```powershell
python -m app.cli --repo "C:\Users\Vladislav\Desktop\interview-review" review-add "Python GIL"
```

Or copy `.env.example` to `.env` and fill `INTERVIEW_REVIEW_PATH`.

New study topic ideas are captured into SQLite through Telegram:
`🗂 Проработка` -> `💡 Темы на изучение`. The bot no longer writes new topics
into `interview-review`; move inbox items into the materials repo manually while
working locally.

## Migrations

The SQLite database is a single local file, but its structure lives in SQL files:

```text
app/core/migrations/
  001_initial.sql
  002_topic_statistics_fields.sql
  003_review_notifications.sql
  004_quiz_sessions.sql
  005_quiz_generation_metadata.sql
  006_study_topic_inbox.sql
  007_instant_quiz_sessions.sql
  008_app_settings.sql
  009_llm_usage_events.sql
  010_mistake_work_items.sql
```

Apply pending migrations with:

```powershell
python -m app.cli migrate
```

## Tests

```powershell
python -m unittest discover -s tests
```

## VPS Deployment

The deployment path is intentionally simple:

```text
Git remote -> VPS git pull -> migrations -> systemd restart
```

The bot runs as a `systemd` service. SQLite stays on the VPS, and a timer creates
daily backups.

### First bootstrap

On a fresh Ubuntu/Debian VPS, first clone the bot repo into a temporary
directory or upload the project archive there. If the repos are private, prepare
SSH deploy keys on the VPS before running bootstrap.

Then run the bootstrap script as root. Provide the bot repository URL, and
optionally the `interview-review` repository URL:

```bash
git clone git@github.com:YOUR_USER/learnkeeper-bot.git /tmp/learnkeeper-bot
cd /tmp/learnkeeper-bot
export BOT_REPO_URL=git@github.com:YOUR_USER/learnkeeper-bot.git
export MATERIALS_REPO_URL=git@github.com:YOUR_USER/interview-review.git
export BOT_GIT_BRANCH=main
export MATERIALS_GIT_BRANCH=main
bash scripts/vps-bootstrap.sh
```

The script installs system packages, Python dependencies, Claude CLI via npm,
builds `whisper.cpp`, creates systemd units and prepares `.env` from
`deploy/env.vps.example`.

After bootstrap:

```bash
sudo nano /opt/learnkeeper/learnkeeper-bot/.env
sudo -u learnkeeper claude --version
sudo -u learnkeeper /opt/learnkeeper/learnkeeper-bot/.venv/bin/python -m app.cli migrate
sudo systemctl start learnkeeper.service
sudo journalctl -u learnkeeper.service -f
```

If Claude CLI needs interactive auth, run it as the `learnkeeper` user once and
then put `CLAUDE_CODE_OAUTH_TOKEN` into `.env`.

### Regular manual deploy

After pushing bot code to the remote repository:

```bash
cd /opt/learnkeeper/learnkeeper-bot
bash scripts/vps-deploy.sh
```

The deploy script pulls the latest bot code, installs dependencies, applies
migrations and restarts `learnkeeper.service`.

### Automatic deploy on push

The repo contains `.github/workflows/deploy.yml`. In GitHub repository secrets,
configure:

```text
VPS_HOST      # server IP or hostname
VPS_USER      # ssh user, usually root or a deploy user
VPS_SSH_KEY   # private SSH key allowed to connect to VPS
VPS_PORT      # optional, defaults to 22
APP_DIR       # optional, defaults to /opt/learnkeeper/learnkeeper-bot
```

After that, every push to `main` deploys the bot to VPS by SSH and runs
`scripts/vps-deploy.sh`.

### interview-review sync on VPS

For materials updates, the bot does not need a full redeploy. Enable this in
the VPS `.env`:

```env
INTERVIEW_REVIEW_PATH=/opt/learnkeeper/interview-review
REPO_GIT_REMOTE=origin
REPO_GIT_BRANCH=main
REPO_PULL_BEFORE_QUIZ=true
REPO_PULL_TIMEOUT_SECONDS=120
```

Before generating a review, instant or daily quiz, LearnKeeper runs a best-effort
`git pull --ff-only` in `interview-review`. If the pull fails, the failure is
logged and quiz generation continues from the local copy already on disk.

### Backups

Bootstrap enables `learnkeeper-backup.timer`. It runs daily and stores compressed
SQLite backups in `/opt/learnkeeper/backups`.

Useful commands:

```bash
sudo systemctl status learnkeeper.service
sudo journalctl -u learnkeeper.service -n 100 --no-pager
sudo systemctl list-timers '*learnkeeper*'
sudo systemctl start learnkeeper-backup.service
```

## Telegram Bot

Install dependencies in the project venv:

```powershell
.venv\bin\python.exe -m pip install -r requirements.txt
```

Fill `.env`:

```env
TELEGRAM_BOT_TOKEN=token_from_botfather
TG_USER_ID=your_numeric_telegram_user_id
REVIEW_TICK_SECONDS=60
QUIZ_QUESTION_COUNT=5
DAILY_QUIZ_TIME=10:20
DAILY_QUIZ_TIMEZONE=Europe/Moscow
```

For real quiz generation through Claude Code subscription auth, add:

```env
LLM_PROVIDER=claude_cli
CLAUDE_BIN=claude
CLAUDE_CODE_OAUTH_TOKEN=token_from_claude_setup_token
CLAUDE_MODEL=claude-sonnet-5
CLAUDE_TIMEOUT_SECONDS=600
ALLOW_PAID_API=false
LLM_INPUT_USD_PER_1M_TOKENS=2
LLM_OUTPUT_USD_PER_1M_TOKENS=10
LLM_USAGE_BUDGET_5H_USD=6.5
LLM_USAGE_BUDGET_DAILY_USD=13
LLM_USAGE_BUDGET_WEEKLY_USD=65
LLM_USAGE_BUDGET_MONTHLY_USD=250
LLM_USAGE_BUDGET_5H_TOKENS=1000000
LLM_USAGE_BUDGET_DAILY_TOKENS=2500000
LLM_USAGE_BUDGET_WEEKLY_TOKENS=12000000
LLM_USAGE_BUDGET_MONTHLY_TOKENS=45000000
```

Pin `CLAUDE_MODEL` (e.g. `claude-sonnet-5`) so token usage is predictable; an
empty value uses Claude Code's default model. The `topic_inbox` normalizer is a
trivial task, so `TOPIC_INBOX_AGENT_MODEL=claude-haiku-4-5` is enough.

To keep token usage down, quiz/mistake/inbox agents run with an explicit
`--disallowedTools` denylist and in an empty working directory, so Claude Code
does a single structured-output call instead of browsing repo files. Quiz
material is capped at 35k chars and mistake-report excerpts at 10k chars.

The `LLM_USAGE_BUDGET_*` values (both USD and token variants) are **local
benchmarks** shown in the Telegram usage report, not real Anthropic limits. The
5h budget also drives a background alert: the bot DMs the owner when rolling 5h
usage crosses 80% and 100%. If a Claude call fails on a usage/rate limit, the bot
now shows a clear "limit reached" notice.

Do not put `ANTHROPIC_API_KEY` in `.env` unless you deliberately want API
billing. With `ALLOW_PAID_API=false`, the bot strips Anthropic API env vars
before invoking Claude CLI and requires `CLAUDE_CODE_OAUTH_TOKEN`.

LLM usage accounting is local and stored in SQLite. Token counts are currently
estimated from prompt/output text size, so the Telegram report is a practical
budget signal, not Anthropic's official billing ledger. The default prices above
track Claude Sonnet 5 introductory API pricing on July 5, 2026. When Anthropic
changes pricing or you switch models, update `LLM_INPUT_USD_PER_1M_TOKENS` and
`LLM_OUTPUT_USD_PER_1M_TOKENS`.

The `LLM_USAGE_BUDGET_*` values are local API-equivalent budget benchmarks, not
hard Claude plan limits. Anthropic exposes five-hour and weekly progress bars in
Claude usage settings, but does not publish exact token quotas for Pro/Max. The
defaults use a practical Claude Code benchmark: roughly `$13` per active day,
`$6.5` per rolling five-hour window, `$65` per five active days, and `$250` per
month. Telegram shows what percentage of those local benchmarks the bot has
consumed.

Check local usage without Telegram:

```powershell
.venv\bin\python.exe -m app.cli llm-usage
```

Voice input is disabled by default so local development does not accidentally
call paid APIs:

```env
STT_PROVIDER=disabled
VOICE_DIR=data/voice
STT_LANGUAGE=ru
STT_PROMPT=Go, Golang, goroutine, mutex, channel, context, runtime, слайсы, мапы
STT_TIMEOUT_SECONDS=180
```

To add review tasks by voice without OpenAI billing, use local `whisper.cpp`.
This keeps audio on your machine and does not call OpenAI/Claude APIs. On
Windows, run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\setup-whisper-cpp.ps1
```

The script downloads the official `whisper.cpp` Windows x64 release and a local
GGML model. Then set the printed values in `.env`, for example:

```env
STT_PROVIDER=whisper_cpp
STT_WHISPER_CPP_BIN=C:\Users\Vladislav\Desktop\ТГ Бот\learnkeeper-bot\tools\whisper.cpp\bin\whisper-cli.exe
STT_WHISPER_CPP_MODEL=C:\Users\Vladislav\Desktop\ТГ Бот\learnkeeper-bot\tools\whisper.cpp\models\ggml-base.bin
FFMPEG_BIN=ffmpeg
```

Check the local STT setup:

```powershell
.venv\bin\python.exe -m app.cli stt-status
```

Test transcription without Telegram:

```powershell
.venv\bin\python.exe -m app.cli stt-preview path\to\voice.oga --provider whisper_cpp
```

`STT_PROVIDER=whisper_cli` is still available if you install the Python/OpenAI
Whisper CLI separately and want the bot to call its local `whisper` command.

To use OpenAI speech-to-text instead, set:

```env
STT_PROVIDER=openai
OPENAI_API_KEY=...
STT_OPENAI_MODEL=gpt-4o-transcribe
FFMPEG_BIN=ffmpeg
```

In Telegram, open `🔁 Повторы` and choose `➕ Добавить повтор`; review tasks use
button selection by block/topic. Voice input is used only after `🗂 Идеи` ->
`➕ Добавить тему`. Voice messages outside this flow are ignored with a hint, so
the bot does not run STT for random audio.

For quiz generation on VPS, `interview-review` can be refreshed right before the
bot reads materials:

```env
REPO_GIT_REMOTE=origin
REPO_GIT_BRANCH=main
REPO_PULL_BEFORE_QUIZ=true
REPO_PULL_TIMEOUT_SECONDS=120
```

This is read-only from the bot's point of view: it runs `git pull --ff-only` and
continues with the local copy if the pull fails.

Topic inbox uses a lighter agent. It does not inspect or modify
`interview-review`; it only rewrites rough text/STT into a clean title and
optional block:

```env
TOPIC_INBOX_AGENT_PROVIDER=claude_cli
TOPIC_INBOX_AGENT_MODEL=
TOPIC_INBOX_AGENT_TIMEOUT_SECONDS=120
```

Use `TOPIC_INBOX_AGENT_PROVIDER=fake` for fully local no-LLM testing.

Mistake review uses a separate agent. It receives the finished quiz session,
wrong answers, explanations and short material excerpts, then returns a
structured report. It does not write to `interview-review`; saved reports live
in SQLite:

```env
MISTAKE_REVIEW_AGENT_PROVIDER=claude_cli
MISTAKE_REVIEW_AGENT_MODEL=
MISTAKE_REVIEW_AGENT_TIMEOUT_SECONDS=180
```

Use `MISTAKE_REVIEW_AGENT_PROVIDER=fake` when you want to test the flow without
calling Claude.

On Windows, if Python cannot find `claude` but PowerShell can, set `CLAUDE_BIN`
to the full command wrapper path, for example:

```env
CLAUDE_BIN=C:\Users\Vladislav\AppData\Roaming\npm\claude.cmd
```

`CLAUDE_CODE_OAUTH_TOKEN` must be a single line in `.env`.

Run polling locally:

```powershell
.venv\bin\python.exe -m app.telegram_bot
```

During quiz generation the console logs show progress:

```text
Claude quiz generation started ...
Claude CLI finished ...
Claude quiz generation parsed ...
```

In Telegram, pressing "Start test" first edits the message to "Generating test";
the first question appears after Claude finishes.

Available commands:

```text
/start
/topics [query]
/review_add <topic>
/instant_quiz
/topic_add <title>
/topic_ideas
/schedule
/due
```

The main Telegram UI uses a persistent reply keyboard with buttons:

```text
📚 Темы
🔁 Повторы
🧪 Тесты
🗂 Проработка
⚙️ Настройки
❔ Помощь
```

Slash commands remain available as a fallback. The top-level buttons open
inline submenus:

- `🔁 Повторы`: add a review, schedule, due reviews, cancel a review.
- `🧪 Тесты`: instant quiz and daily random quiz toggle.
- `🗂 Проработка`: save future study topics and review saved mistake reports.
- `⚙️ Настройки`: daily random quiz toggle and local LLM usage statistics.

Old flat button labels are still accepted as fallback text actions.

When a review task is due, the bot checks in the background and sends a message
with a "Start test" button. Pressing it edits that same message into the first
quiz question. Each answer edits the same message into the next question, and
the final answer edits it into the report.

If the final report has wrong answers, Telegram shows a `Разобрать ошибки`
button. The agent can generate a full mistake report; after preview you can save
it under `🗂 Проработка` → `🧩 Работа над ошибками`, mark it done, or delete it.

`quiz-preview` lets you test the generator without Telegram and without saving a
quiz session:

```powershell
.venv\bin\python.exe -m app.cli quiz-preview "слайсы" --questions 5
```

## Architecture

The first implementation is a modular monolith:

```text
app/
  core/
    db.py
    repo.py
    llm.py
  features/
    quiz/
      factory.py
      generator.py
      models.py
      service.py
    review_tasks/
      models.py
      service.py
    mistake_work/
      agent.py
      factory.py
      models.py
      service.py
    topic_inbox/
      agent.py
      factory.py
      models.py
      service.py
  adapters/
    telegram/
```

Business logic lives in feature services. Telegram is only an adapter over the
same services.
