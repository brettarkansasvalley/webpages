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

# --- Off-box copy: force-push latest snapshot to GitHub branch db-backups ---
# Single amended commit so the branch never accumulates history; local
# 14-day rotation above remains the point-in-time archive.
GH_REMOTE="git@github.com:brettarkansasvalley/webpages.git"
GH_DIR="$BACKUP_ROOT/github-mirror"
if [[ ! -d "$GH_DIR/.git" ]]; then
  git init -q -b db-backups "$GH_DIR"
  git -C "$GH_DIR" remote add origin "$GH_REMOTE"
  git -C "$GH_DIR" config user.name "toasty-backup"
  git -C "$GH_DIR" config user.email "backup@zucklakeapp"
  printf 'Nightly gzipped SQLite backups (latest only; older copies live on the server in /home/ubuntu/db_backups/).\n' > "$GH_DIR/README.md"
fi
cp "$DEST"/*.gz "$GH_DIR/"
git -C "$GH_DIR" add -A
if git -C "$GH_DIR" rev-parse HEAD >/dev/null 2>&1; then
  git -C "$GH_DIR" commit -q --amend -m "DB backup $STAMP"
else
  git -C "$GH_DIR" commit -q -m "DB backup $STAMP"
fi
git -C "$GH_DIR" push -q -f origin db-backups
echo "[backup] pushed snapshot to GitHub branch db-backups"

echo "[backup] complete: $(date '+%Y-%m-%d %H:%M:%S')"
