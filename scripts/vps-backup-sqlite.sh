#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/learnkeeper/learnkeeper-bot}"
BACKUP_DIR="${BACKUP_DIR:-/opt/learnkeeper/backups}"
DB_PATH="${DB_PATH:-$APP_DIR/data/learnkeeper.sqlite3}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
  echo "SQLite database not found: $DB_PATH" >&2
  exit 0
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
TMP_BACKUP="$BACKUP_DIR/learnkeeper-$STAMP.sqlite3"

sqlite3 "$DB_PATH" ".backup '$TMP_BACKUP'"
gzip -f "$TMP_BACKUP"

find "$BACKUP_DIR" -type f -name 'learnkeeper-*.sqlite3.gz' -mtime "+$KEEP_DAYS" -delete

echo "Backup created: $TMP_BACKUP.gz"
