# gr8base community

A simple, server-rendered web app for discovering and contributing family-friendly climbing crags. Families need reliable, easy-to-find information that tells them quickly whether a place suits their children. Production runs at [gr8base.com](https://gr8base.com).

The project is open source and everyone is welcome to help:

- [Development plan](https://github.com/ripertio/gr8base-community/milestones): see what we are working on now and what is planned next
- [Feature request or bug report](https://github.com/ripertio/gr8base-community/issues/new/choose): tell us about an idea, a missing crag feature, or something that does not work. No technical knowledge needed, just describe what you saw or wish for
- [Contributing](CONTRIBUTING.md): Want to contribute? read first.

## What it does

**For everyone**
- Browse published crags, search by name, filter by area and by family rating (babies, ages 2-4, ages 5+)
- Crag detail page with photo gallery (lightbox), approach and base-area features, orientation, parking, map location link, family notes
- Documentation pages written in Markdown (`content/`, served under `/docs/`), including terms, privacy and impressum

**For registered users** (django-allauth, e-mail verification, password reset)
- Create crags, edit and delete their own, upload photos with a category
- Save as draft and submit for review; a "my crags" overview

**For staff**
- Review submissions in the Django admin (publish or reject), correct data, manage areas, features and users
- `/stats/`: charts of registered users and crags over time

**Photos** are validated and processed on upload: max. 15 MB, EXIF rotation applied, resized to 1,600 px, re-encoded as WebP; HEIC/HEIF is supported. Details in [docs/technical-stack.md](docs/technical-stack.md).

What a crag entry contains: [docs/crag-details.md](docs/crag-details.md).

## Tech stack

Python 3.13, Django 5.2, Django templates + Pico CSS, PostgreSQL 17, django-allauth (Argon2 hashing), Pillow/pillow-heif, WhiteNoise, Gunicorn, Docker Compose, Caddy behind a Cloudflare tunnel, Resend (via django-anymail) for e-mail.

## Getting started (development)

Everything runs in Docker; nothing needs to be installed into a local Python environment. On macOS, [colima](https://github.com/abiosoft/colima) works as the Docker runtime.

```bash
./scripts/dev.sh            # starts colima if needed, loads data-dev on first run, runs the app
./scripts/dev.sh --reset    # replace the local dev database with data-dev/dev.dump
```

The app is then at <http://localhost:8010> (change with `WEB_PORT`). Log in as `dev-root` / `dev-root` (superuser, created by `seed_dev_users`, only works with `DEBUG=True`).

Without the script:

```bash
export COMPOSE_FILE=docker-compose.dev.yml
docker compose up --build
docker compose exec web python manage.py test
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py createsuperuser
docker compose down -v      # wipe the dev database
```

`data-dev/` holds a sample database dump and media and is tracked on purpose, so a fresh clone has realistic data.

## Configuration

Settings are read from environment variables (see `gr8base/settings.py`). For production copy [.env.example](.env.example) to `.env`:

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Django secret key (required) |
| `POSTGRES_PASSWORD` | Database password |
| `RESEND_API_KEY` | Sending e-mail (verification, password reset) |
| `CLOUDFLARE_TUNNEL_TOKEN` | Tunnel to the Caddy container |
| `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Set by the compose files |
| `MEDIA_DIR` | Host path for uploaded media (default `./data/media`) |

## Deployment, backup and restore

`docker-compose.yml` runs web (Gunicorn), Caddy, cloudflared and PostgreSQL. A health check is served at `/healthz/`. Deploy, backup and restore scripts are documented in [scripts/README.md](scripts/README.md).

## Project layout

| Path | Content |
| --- | --- |
| `gr8base/` | Project settings, URLs, docs pages, health check |
| `crags/` | Crags, areas, photos, features; views, forms, templates, `seed_dev_users` command |
| `accounts/` | Custom user model and user profiles (bio, avatar, public/private) |
| `stats/` | Staff statistics page (users and crags over time) |
| `content/` | Markdown documentation pages |
| `templates/`, `static/` | Base templates, CSS, JavaScript |
| `scripts/` | Dev start, backup, restore, deploy |
| `data-dev/` | Sample dump and media for development |
| `docs/` | Crag data model and technical notes |

## Principles

Simple server-rendered architecture, mobile-first UX, PostgreSQL as the system of record, community-contributed content, maintainability over complexity, recovery and portability over vendor lock-in.
