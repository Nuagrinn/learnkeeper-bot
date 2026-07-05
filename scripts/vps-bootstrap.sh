#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-learnkeeper}"
APP_HOME="${APP_HOME:-/home/$APP_USER}"
BASE_DIR="${BASE_DIR:-/opt/learnkeeper}"
APP_DIR="${APP_DIR:-$BASE_DIR/learnkeeper-bot}"
MATERIALS_DIR="${MATERIALS_DIR:-$BASE_DIR/interview-review}"
BOT_REPO_URL="${BOT_REPO_URL:-}"
BOT_GIT_BRANCH="${BOT_GIT_BRANCH:-main}"
MATERIALS_REPO_URL="${MATERIALS_REPO_URL:-}"
MATERIALS_GIT_BRANCH="${MATERIALS_GIT_BRANCH:-main}"
WHISPER_MODEL="${WHISPER_MODEL:-base}"
INSTALL_CLAUDE_CLI="${INSTALL_CLAUDE_CLI:-1}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root or through sudo." >&2
  exit 1
fi

if [ -z "$BOT_REPO_URL" ]; then
  echo "Set BOT_REPO_URL to the git URL of learnkeeper-bot." >&2
  exit 1
fi

apt-get update
apt-get install -y \
  build-essential \
  ca-certificates \
  cmake \
  curl \
  ffmpeg \
  git \
  nodejs \
  npm \
  python3 \
  python3-pip \
  python3-venv \
  sqlite3 \
  sudo

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --create-home --home-dir "$APP_HOME" --shell /bin/bash "$APP_USER"
fi

mkdir -p "$BASE_DIR"
chown -R "$APP_USER:$APP_USER" "$BASE_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git clone --branch "$BOT_GIT_BRANCH" "$BOT_REPO_URL" "$APP_DIR"
else
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only origin "$BOT_GIT_BRANCH"
fi

if [ -n "$MATERIALS_REPO_URL" ]; then
  if [ ! -d "$MATERIALS_DIR/.git" ]; then
    sudo -u "$APP_USER" git clone --branch "$MATERIALS_GIT_BRANCH" "$MATERIALS_REPO_URL" "$MATERIALS_DIR"
  else
    sudo -u "$APP_USER" git -C "$MATERIALS_DIR" pull --ff-only origin "$MATERIALS_GIT_BRANCH"
  fi
fi

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

if [ "$INSTALL_CLAUDE_CLI" = "1" ] && ! command -v claude >/dev/null 2>&1; then
  npm install -g @anthropic-ai/claude-code
fi

sudo -u "$APP_USER" APP_DIR="$APP_DIR" bash "$APP_DIR/scripts/setup-whisper-cpp-linux.sh" "$WHISPER_MODEL"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/deploy/env.vps.example" "$APP_DIR/.env"
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Fill secrets before starting the service."
fi

install -m 0644 "$APP_DIR/deploy/systemd/learnkeeper.service" /etc/systemd/system/learnkeeper.service
install -m 0644 "$APP_DIR/deploy/systemd/learnkeeper-backup.service" /etc/systemd/system/learnkeeper-backup.service
install -m 0644 "$APP_DIR/deploy/systemd/learnkeeper-backup.timer" /etc/systemd/system/learnkeeper-backup.timer

systemctl daemon-reload
systemctl enable learnkeeper.service
systemctl enable --now learnkeeper-backup.timer

echo "Bootstrap complete."
echo "Next:"
echo "1. Edit $APP_DIR/.env"
echo "2. Authorize Claude CLI as $APP_USER if needed"
echo "3. Run: systemctl start learnkeeper.service"
