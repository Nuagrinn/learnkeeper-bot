#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/learnkeeper/learnkeeper-bot}"
REMOTE="${BOT_GIT_REMOTE:-origin}"
BRANCH="${BOT_GIT_BRANCH:-main}"
SERVICE="${SERVICE_NAME:-learnkeeper.service}"

cd "$APP_DIR"
git config --global --add safe.directory "$APP_DIR" || true

echo "Fetching bot repository..."
git fetch "$REMOTE" "$BRANCH"
git pull --ff-only "$REMOTE" "$BRANCH"

echo "Installing Python dependencies..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "Applying migrations..."
.venv/bin/python -m app.cli migrate

echo "Restarting $SERVICE..."
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE"
  sudo systemctl --no-pager --lines=40 status "$SERVICE"
else
  echo "systemctl not found; start the bot manually." >&2
fi
