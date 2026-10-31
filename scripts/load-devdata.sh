#!/usr/bin/env bash
# Load the exported production copy into the local dev environment.
#
# Run on your machine from anywhere in the project:
#   ./scripts/load-devdata.sh          # asks before wiping the dev database
#   ./scripts/load-devdata.sh --yes    # no question
#
# Expects (from export-devdata.sh, copied via rsync):
#   data-dev/dev.dump
#   data-dev/media/      mounted as /app/media by docker-compose.dev.yml
#
# Only ever touches the dev compose project (gr8base-dev), never production.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.dev.yml)
DB_NAME="familienfelsen"
DB_USER="familienfelsen"
DUMP="data-dev/dev.dump"
MEDIA_DIR="data-dev/media"

if [[ ! -f "$DUMP" ]]; then
    echo "ERROR: $DUMP not found. Copy it from the server first." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not reachable. Start it first: colima start" >&2
    exit 1
fi

if [[ "${1:-}" != "--yes" ]]; then
    [[ -f data-dev/MANIFEST.txt ]] && cat data-dev/MANIFEST.txt && echo
    read -r -p "This replaces the local dev database '$DB_NAME'. Continue? [y/N] " answer
    [[ "$answer" =~ ^[yY]$ ]] || { echo "Aborted."; exit 1; }
fi

echo "==> Starting database"
"${COMPOSE[@]}" up -d --wait db

echo "==> Stopping web so nothing holds a connection"
"${COMPOSE[@]}" stop web >/dev/null 2>&1 || true

echo "==> Recreating database '$DB_NAME'"
"${COMPOSE[@]}" exec -T db dropdb -U "$DB_USER" --if-exists --force "$DB_NAME"
"${COMPOSE[@]}" exec -T db createdb -U "$DB_USER" "$DB_NAME"

echo "==> Restoring $DUMP"
"${COMPOSE[@]}" exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" \
    --no-owner --no-acl --exit-on-error < "$DUMP"

echo "==> Applying migrations newer than the dump"
"${COMPOSE[@]}" run --rm --no-deps web python manage.py migrate --noinput

echo "==> Creating dev-root and assigning ownerless crags and photos"
"${COMPOSE[@]}" run --rm --no-deps web python manage.py seed_dev_users

echo "==> Checking photo files"
missing=0
while IFS= read -r path; do
    [[ -n "$path" && ! -f "$MEDIA_DIR/$path" ]] && missing=$((missing + 1))
done < <("${COMPOSE[@]}" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At \
    -c "SELECT image FROM crags_photo")
if (( missing > 0 )); then
    echo "   WARNING: $missing photo files are missing in $MEDIA_DIR" >&2
fi

echo "==> Starting web"
"${COMPOSE[@]}" up -d web

echo
echo "Done: http://localhost:8010  (log in as dev-root / dev-root)"
