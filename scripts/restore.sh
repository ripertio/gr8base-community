#!/usr/bin/env bash
# Restore the database and uploaded media from a backup made by backup.sh.
#
# Run on the SERVER from anywhere in the project:
#   ./scripts/restore.sh                       # newest backup in $BACKUP_DIR
#   ./scripts/restore.sh 2026-10-28_031500     # a specific backup by name
#   ./scripts/restore.sh /path/to/backup-dir   # a backup directory anywhere
#   ./scripts/restore.sh --yes [backup]        # no question
#   ./scripts/restore.sh --rollback            # undo the last deploy (code + data)
#   ./scripts/restore.sh --with-code [backup]  # restore a backup AND its commit
#
# --rollback reads the newest deploy line in $BACKUP_DIR/deploy.log (written by
# deploy_production.sh), resets the checked-out branch to its prev= commit,
# rebuilds web and restores its backup=. That pair is a consistent state: the
# backup was taken before the deploy's migrations ran. Fix or revert the bad
# commit on origin first, or the next deploy brings it straight back.
# Data written since that backup is lost (the pre-restore copy below keeps it).
#
# --with-code looks the chosen backup (default: newest) up in the same log and
# resets to the commit recorded for it: prev= of a deploy line, commit= of a
# cron backup line. Fails if the backup has no log entry.
#
# Both refuse to run when COMPOSE_FILE names a dev file (override:
# ALLOW_DEV_DEPLOY=1), because they run git reset --hard.
#
# Expects the backup directory to contain db.dump and media.tar.gz.
# env.backup is NOT restored automatically (it holds secrets and may differ
# from the current .env); copy it over by hand if you are rebuilding a server.
#
# Before anything is replaced, the current database and media are saved to
# $BACKUP_DIR/pre-restore_<timestamp>/ so a wrong restore can be undone.
# Those copies are removed after $KEEP_DAYS days (default 14), like backups.
#
# Uses the same settings as backup.sh (environment, then .env, then defaults),
# and the compose file selected by COMPOSE_FILE (default docker-compose.yml).
set -euo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$0")/.."

# Same lookup as backup.sh: environment first, then .env, then the default.
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
MEDIA_DIR="$(setting MEDIA_DIR data/media)"
KEEP_DAYS="$(setting KEEP_DAYS 14)"

yes=false
rollback=false
with_code=false
source_arg=""
for arg in "$@"; do
    case "$arg" in
        --yes) yes=true ;;
        --rollback) rollback=true ;;
        --with-code) with_code=true ;;
        -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$SELF"; exit 0 ;;
        -*) echo "Unknown option: $arg (see --help)" >&2; exit 1 ;;
        *) source_arg="$arg" ;;
    esac
done
$rollback && [[ -n "$source_arg" ]] && { echo "ERROR: --rollback picks the backup itself" >&2; exit 1; }
$rollback && $with_code && { echo "ERROR: use either --rollback or --with-code" >&2; exit 1; }

if $rollback || $with_code; then
    # These run git reset --hard: never against the dev working tree.
    compose_file="$(setting COMPOSE_FILE docker-compose.yml)"
    if [[ "$compose_file" == *dev* && -z "${ALLOW_DEV_DEPLOY:-}" ]]; then
        echo "ERROR: COMPOSE_FILE=$compose_file looks like the dev setup; refusing to reset code." >&2
        echo "       (set ALLOW_DEV_DEPLOY=1 to override, e.g. in a scratch clone)" >&2
        exit 1
    fi
fi

# Resolve which backup to restore
CODE_COMMIT=""
CODE_ACTION=""
if $rollback; then
    LOG="$BACKUP_DIR/deploy.log"
    [[ -f "$LOG" ]] || { echo "ERROR: $LOG not found (no deploy has been logged yet)" >&2; exit 1; }
    # Deploy lines only; earlier rollback lines are skipped.
    line="$(grep -E ' (ok|FAILED\([0-9]+\)) prev=[0-9a-f]+ new=[0-9a-f]+ backup=' "$LOG" | tail -1 || true)"
    [[ -n "$line" ]] || { echo "ERROR: no deploy entry in $LOG" >&2; exit 1; }
    CODE_ACTION="rollback"
    CODE_COMMIT="$(sed -n 's/.* prev=\([0-9a-f]*\) .*/\1/p' <<< "$line")"
    SRC="$(sed -n 's/.* backup=//p' <<< "$line")"
    [[ -d "$SRC" ]] || { echo "ERROR: backup $SRC from the last deploy no longer exists (pruned?)" >&2; exit 1; }
    git cat-file -e "$CODE_COMMIT^{commit}" 2>/dev/null \
        || { echo "ERROR: commit $CODE_COMMIT is not in this repository" >&2; exit 1; }
    echo "Last deploy: $line"
elif [[ -z "$source_arg" ]]; then
    # Timestamped names sort chronologically; skip the pre-restore safety copies
    [[ -d "$BACKUP_DIR" ]] || { echo "ERROR: backup directory $BACKUP_DIR does not exist (run backup.sh first)" >&2; exit 1; }
    SRC="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*_[0-9]*' | sort | tail -1)"
    [[ -n "$SRC" ]] || { echo "ERROR: no backups found in $BACKUP_DIR" >&2; exit 1; }
elif [[ -d "$source_arg" ]]; then
    SRC="${source_arg%/}"
else
    SRC="$BACKUP_DIR/$source_arg"
fi

if $with_code; then
    LOG="$BACKUP_DIR/deploy.log"
    [[ -f "$LOG" ]] || { echo "ERROR: $LOG not found, cannot tell which commit goes with $SRC" >&2; exit 1; }
    # Entries ending in exactly "backup=$SRC": a deploy or a cron backup line.
    line="$(WANT=" backup=$SRC" awk 'BEGIN { w = ENVIRON["WANT"] }
            { i = index($0, w); if (i && i + length(w) - 1 == length($0)) print }' "$LOG" \
        | grep -E ' (ok|FAILED\([0-9]+\)) prev=| backup commit=' | tail -1 || true)"
    [[ -n "$line" ]] || { echo "ERROR: no log entry for $SRC in $LOG; restore without --with-code" >&2; exit 1; }
    if [[ "$line" == *" backup commit="* ]]; then
        CODE_COMMIT="$(sed -n 's/.* commit=\([0-9a-f]*\) .*/\1/p' <<< "$line")"
    else
        # Deploy line: the backup was taken before its migrations, i.e. under prev.
        CODE_COMMIT="$(sed -n 's/.* prev=\([0-9a-f]*\) .*/\1/p' <<< "$line")"
    fi
    [[ -n "$CODE_COMMIT" ]] || { echo "ERROR: no commit recorded in: $line" >&2; exit 1; }
    git cat-file -e "$CODE_COMMIT^{commit}" 2>/dev/null \
        || { echo "ERROR: commit $CODE_COMMIT is not in this repository" >&2; exit 1; }
    CODE_ACTION="restore"
    echo "Log entry: $line"
fi

[[ -s "$SRC/db.dump" ]]       || { echo "ERROR: $SRC/db.dump not found" >&2; exit 1; }
[[ -f "$SRC/media.tar.gz" ]]  || { echo "ERROR: $SRC/media.tar.gz not found" >&2; exit 1; }

echo "==> Checking that the dump is readable"
docker compose exec -T db pg_restore --list < "$SRC/db.dump" >/dev/null \
    || { echo "ERROR: $SRC/db.dump is not a valid dump (is the db container running?)" >&2; exit 1; }
tar -tzf "$SRC/media.tar.gz" >/dev/null

if ! $yes; then
    echo
    echo "Restore from: $SRC ($(du -sh "$SRC" | cut -f1))"
    [[ -z "$CODE_COMMIT" ]] || echo "Code: git reset --hard $CODE_COMMIT (discards local changes), then rebuild web."
    echo "This REPLACES database '$DB_NAME' and the contents of $MEDIA_DIR."
    read -r -p "Continue? [y/N] " answer
    [[ "$answer" =~ ^[yY]$ ]] || { echo "Aborted."; exit 1; }
fi

umask 077   # safety copy contains user data
STAMP="$(date +%F_%H%M%S)"
SAFETY="$BACKUP_DIR/pre-restore_$STAMP"
mkdir -p "$SAFETY"

echo "==> Saving current state to $SAFETY"
docker compose exec -T db pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$SAFETY/db.dump"
[[ -s "$SAFETY/db.dump" ]] || { echo "ERROR: empty safety dump, nothing was changed" >&2; exit 1; }
if [[ -d "$MEDIA_DIR" ]]; then
    tar -czf "$SAFETY/media.tar.gz" -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")"
fi

echo "==> Removing pre-restore copies older than $KEEP_DAYS days"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'pre-restore_*' \
    -mtime +"$KEEP_DAYS" -exec rm -rf {} +

if [[ -n "$CODE_COMMIT" ]]; then
    # Before stopping web, so the (slow) build does not add downtime. The image
    # must match the old code or the migrate below would re-apply new migrations.
    HEAD_BEFORE="$(git rev-parse HEAD)"
    echo "==> Resetting code to $CODE_COMMIT"
    git reset --hard "$CODE_COMMIT"
    docker compose build web
fi

echo "==> Stopping web so nothing holds a connection"
docker compose stop web

echo "==> Recreating database '$DB_NAME'"
docker compose exec -T db dropdb -U "$DB_USER" --if-exists --force "$DB_NAME"
docker compose exec -T db createdb -U "$DB_USER" "$DB_NAME"

echo "==> Restoring database"
docker compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" \
    --no-owner --no-acl --exit-on-error < "$SRC/db.dump"

echo "==> Restoring media"
# Replace the contents, not the directory: it may be a bind mount target.
mkdir -p "$MEDIA_DIR"
find "$MEDIA_DIR" -mindepth 1 -delete
tar -xzf "$SRC/media.tar.gz" -C "$(dirname "$MEDIA_DIR")"

echo "==> Applying migrations newer than the backup"
docker compose run --rm --no-deps web python manage.py migrate --noinput

echo "==> Starting web"
docker compose up -d web

if [[ -n "$CODE_COMMIT" ]]; then
    entry="$(date +%FT%T%z) $CODE_ACTION from=$HEAD_BEFORE to=$CODE_COMMIT backup=$SRC"
    echo "$entry" >> "$BACKUP_DIR/deploy.log"
    echo "$entry" >> gr8base-backup.log
fi

echo
echo "Done: restored $SRC"
echo "Previous state kept in $SAFETY"
[[ -f "$SRC/env.backup" ]] && echo "Note: env.backup was not applied; compare it with .env if needed."
