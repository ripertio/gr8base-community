#!/usr/bin/env bash
# Back up the production database, uploaded media and .env.
#
# Run on the SERVER from anywhere in the project:
#   ./scripts/backup.sh
#
# Creates   $BACKUP_DIR/YYYY-MM-DD_HHMMSS/{db.dump,media.tar.gz,env.backup}
# Keeps     the newest $KEEP_DAYS days locally (default 14).
# Off-site  set BACKUP_REMOTE to an rsync target or an rclone remote, e.g.
#             BACKUP_REMOTE="user@host:/backups/gr8base"      (rsync over ssh)
#             BACKUP_REMOTE="rclone:b2remote:bucket/gr8base"   (rclone)
#           A backup on the same disk does not survive losing the server.
# Alerts   set BACKUP_HEARTBEAT_URL (e.g. a healthchecks.io ping URL). It is
#          requested only after a fully successful run, so a failed or missing
#          backup makes the monitoring service alert you.
#
# Cron example (daily 03:15):
#   15 3 * * * /path/to/gr8base-community/scripts/backup.sh > /dev/null
#
# Log      appends "<time> backup commit=<HEAD> backup=<dir>" to $BACKUP_DIR/deploy.log
#          and ./gr8base-backup.log (same files deploy_production.sh writes to).
#          Entries whose backup directory has been pruned are removed again.
#
# Restore:
#   ./scripts/restore.sh [backup-name-or-dir]    # newest backup if omitted
#   restore.sh first saves the current state to $BACKUP_DIR/pre-restore_<timestamp>/
#   (see restore.sh --help). Those copies are pruned by the same $KEEP_DAYS rule.
set -euo pipefail

cd "$(dirname "$0")/.."

# Settings come from the environment first, then .env, then the default below.
# .env is not sourced: it is docker-style and may contain inline comments that
# bash can't parse. Keep values plain (no quotes, no trailing comments).
env_get() {
    grep -E "^[[:space:]]*$1=" .env 2>/dev/null | head -1 | cut -d= -f2- \
        | sed -E 's/[[:space:]]*#.*//; s/^[[:space:]]+|[[:space:]]+$//g' || true
}
setting() {   # setting NAME DEFAULT
    local value="${!1:-$(env_get "$1")}"
    echo "${value:-$2}"
}

DB_NAME="$(setting POSTGRES_DB familienfelsen)"
DB_USER="$(setting POSTGRES_USER familienfelsen)"
BACKUP_DIR="$(setting BACKUP_DIR "$HOME/gr8base-backups")"
KEEP_DAYS="$(setting KEEP_DAYS 14)"
BACKUP_REMOTE="$(setting BACKUP_REMOTE "")"
BACKUP_HEARTBEAT_URL="$(setting BACKUP_HEARTBEAT_URL "")"
MEDIA_DIR="$(setting MEDIA_DIR data/media)"
# Dev: put MEDIA_DIR=./data-dev/media and COMPOSE_FILE=docker-compose.dev.yml in .env

STAMP="$(date +%F_%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"
umask 077   # backups contain user data and secrets

echo "==> [$STAMP] Dumping database"
# Custom format: compressed, consistent snapshot, restorable with pg_restore.
docker compose exec -T db pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$DEST/db.dump"
[[ -s "$DEST/db.dump" ]] || { echo "ERROR: empty dump" >&2; exit 1; }

echo "==> Archiving media"
tar -czf "$DEST/media.tar.gz" -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")"

echo "==> Saving .env (secrets are not in git)"
cp .env "$DEST/env.backup"

echo "==> Verifying dump is readable"
docker compose exec -T db pg_restore --list < "$DEST/db.dump" >/dev/null

# Record which commit was checked out, so a backup can be matched to its code.
# deploy_production.sh logs its own line (with prev/new) and sets BACKUP_SKIP_LOG.
if [[ -z "${BACKUP_SKIP_LOG:-}" ]]; then
    commit="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
    entry="$(date +%FT%T%z) backup commit=$commit backup=$DEST"
    echo "$entry" >> "$BACKUP_DIR/deploy.log"
    echo "$entry" >> gr8base-backup.log   # relative to the project root
fi

echo "==> Removing local backups (and pre-restore copies) older than $KEEP_DAYS days"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +

# Drop log lines whose backup directory is gone, so the logs only list backups
# that can still be restored. Lines without a backup= are kept.
prune_log() {   # prune_log FILE
    [[ -f "$1" ]] || return 0
    local tmp line dir
    tmp="$(mktemp)"
    while IFS= read -r line || [[ -n "$line" ]]; do
        dir="${line##* backup=}"
        if [[ "$line" != *" backup="* || "$dir" == none || -d "$dir" ]]; then
            printf '%s\n' "$line" >> "$tmp"
        fi
    done < "$1"
    cat "$tmp" > "$1"   # keep the file's mode and owner
    rm -f "$tmp"
}
echo "==> Removing log entries for backups that no longer exist"
prune_log "$BACKUP_DIR/deploy.log"
prune_log gr8base-backup.log

if [[ -n "$BACKUP_REMOTE" ]]; then
    echo "==> Copying off-site to $BACKUP_REMOTE"
    if [[ "$BACKUP_REMOTE" == rclone:* ]]; then
        rclone copy "$BACKUP_DIR" "${BACKUP_REMOTE#rclone:}"
    else
        rsync -a --delete "$BACKUP_DIR/" "$BACKUP_REMOTE/"
    fi
else
    echo "WARNING: BACKUP_REMOTE not set - backup exists only on this machine" >&2
fi

if [[ -n "$BACKUP_HEARTBEAT_URL" ]]; then
    echo "==> Pinging heartbeat"
    curl -fsS -m 10 --retry 3 -o /dev/null "$BACKUP_HEARTBEAT_URL" \
        || echo "WARNING: heartbeat ping failed" >&2
fi

echo "Done: $DEST ($(du -sh "$DEST" | cut -f1))"
