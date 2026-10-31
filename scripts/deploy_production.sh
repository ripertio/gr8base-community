#!/usr/bin/env bash
# Deploy the latest main on the SERVER: pull, build, back up, migrate, restart.
#
# Run on the SERVER from anywhere in the project:
#   ./scripts/deploy_production.sh
# or from your machine:
#   ./scripts/deploy_on_server_with_ssh.sh
#
# Every deploy appends one line to $BACKUP_DIR/deploy.log (next to the backups)
# and to gr8base-backup.log in the project root:
#   <time> ok|FAILED(<code>) prev=<commit before> new=<commit after> backup=<dir>
# The backup is taken just before migrate, so it matches the prev commit.
# ./scripts/restore.sh --rollback uses that line to go back to a working state.
set -euo pipefail

cd "$(dirname "$0")/.."

# This pulls main and resets state: never run it against the dev setup, where
# the working tree holds your own branch and uncommitted work.
compose_file="${COMPOSE_FILE:-$(grep -E '^[[:space:]]*COMPOSE_FILE=' .env 2>/dev/null | head -1 | cut -d= -f2- | sed -E 's/[[:space:]]*#.*//' || true)}"
if [[ "$compose_file" == *dev* && -z "${ALLOW_DEV_DEPLOY:-}" ]]; then
    echo "ERROR: COMPOSE_FILE=$compose_file looks like the dev setup; refusing to deploy." >&2
    echo "       (set ALLOW_DEV_DEPLOY=1 to override, e.g. in a scratch clone)" >&2
    exit 1
fi

# Wrapped in a function so bash has read the whole script before git replaces it.
main() {
    PREV="$(git rev-parse HEAD)"
    BACKUP="none"
    LOG=""
    log_deploy() {
        local status=$?
        [[ -n "$LOG" ]] || return 0
        local result="ok"
        [[ $status -eq 0 ]] || result="FAILED($status)"
        local line
        line="$(date +%FT%T%z) $result prev=$PREV new=$(git rev-parse HEAD) backup=$BACKUP"
        echo "$line" >> "$LOG"
        echo "$line" >> gr8base-backup.log   # relative to the project root
        echo "==> Logged to $LOG and $PWD/gr8base-backup.log"
        echo "    $line"
    }
    trap log_deploy EXIT

    echo "previous: $PREV"
    git fetch origin main
    git pull --ff-only origin main
    docker compose build web

    # backup.sh prints "Done: <dir> (<size>)" last; that is how we learn the dir.
    local out
    out="$(mktemp)"
    BACKUP_SKIP_LOG=1 ./scripts/backup.sh | tee "$out"
    BACKUP="$(sed -n 's/^Done: \(.*\) (.*)$/\1/p' "$out")"
    rm -f "$out"
    [[ -d "$BACKUP" ]] || { echo "ERROR: could not determine backup dir" >&2; exit 1; }
    # Outside the repo, and not pruned with the old backups.
    LOG="$(dirname "$BACKUP")/deploy.log"

    docker compose run --rm web python manage.py migrate --noinput
    docker compose up -d web
}

main "$@"
exit
