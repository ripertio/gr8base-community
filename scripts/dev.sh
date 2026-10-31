#!/usr/bin/env bash
# Start the local development environment.
#
#   ./dev.sh           start colima if needed, load the dev data on first run, run the app
#   ./dev.sh --reset   replace the local dev database with data-dev/dev.dump, then run the app
#
# The app runs in the foreground at http://localhost:8010 (WEB_PORT to change) (Ctrl+C stops it).
# Log in as dev-root / dev-root.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.dev.yml)
DB_NAME="familienfelsen"
DB_USER="familienfelsen"

reset=false
case "${1:-}" in
    "") ;;
    --reset) reset=true ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 1 ;;
esac

if ! docker info >/dev/null 2>&1; then
    if command -v colima >/dev/null 2>&1; then
        echo "==> Starting colima"
        colima start
    else
        echo "ERROR: Docker is not reachable and colima is not installed." >&2
        exit 1
    fi
fi

echo "==> Building and starting database"
"${COMPOSE[@]}" build web
"${COMPOSE[@]}" up -d --wait db

# A fresh volume has no tables yet: that's the first run
has_data="$("${COMPOSE[@]}" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At \
    -c "SELECT to_regclass('public.crags_crag') IS NOT NULL")"

if $reset || [[ "$has_data" != "t" ]]; then
    ./scripts/load-devdata.sh --yes
fi

echo "==> Running app (Ctrl+C to stop)"
"${COMPOSE[@]}" up web
