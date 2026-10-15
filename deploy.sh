#!/usr/bin/env bash
set -euo pipefail

docker compose build web
docker compose run --rm web python manage.py migrate
docker compose up -d --force-recreate