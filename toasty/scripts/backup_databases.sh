#!/usr/bin/env bash
# Nightly SQLite backups with rotation. Run from cron as the ubuntu user.
# Uses sqlite3 .backup (safe on live WAL databases), gzips, keeps 14 days.
set -euo pipefail

BACKUP_ROOT="/home/ubuntu/db_backups"
KEEP_DAYS=14
STAMP="$(date +%Y%m%d)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"

backup_db() {
  local src="$1"
  local name
  name="$(basename "$src")"
  if [[ ! -f "$src" ]]; then
    echo "[backup] SKIP missing: $src"
    return
  fi
  sqlite3 "$src" ".backup '$DEST/$name'"
  gzip -f "$DEST/$name"
  echo "[backup] $src -> $DEST/$name.gz ($(du -h "$DEST/$name.gz" | cut -f1))"
}

backup_db /home/ubuntu/new_toasty/toasty/webapp/webapp.db
backup_db /home/ubuntu/new_toasty/toasty/tip_distribution.db

# Drop daily folders older than KEEP_DAYS
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +

echo "[backup] complete: $(date '+%Y-%m-%d %H:%M:%S')"
