# Technical Stack

## Application
- **Python 3.13 and Django 5.2** power the server-rendered web app, forms, routing, admin, and database models.
- **Django Templates, Pico CSS, custom CSS, and JavaScript** provide the responsive UI without a separate frontend framework. JavaScript is used for the photo lightbox; pages still render on the server.
- **django-allauth** provides account login and registration. **Argon2** is configured as the preferred password hasher.
- **WhiteNoise** serves collected static assets (CSS and JavaScript) from Django alongside Gunicorn.

## Data and deployment
- **PostgreSQL 17** stores application data; Django accesses it through its ORM and the psycopg driver.
- **Docker Compose** runs the web and database containers. Bind-mounted data directories persist database files and uploaded media.
- **Caddy** routes HTTPS traffic to the web container.
- **Gunicorn** production application server handling webrequests.

## Image processing
**Pillow** processes uploaded photos in `process_image` to limit storage and standardize display:
- Rejects files larger than 15 MB, unsupported formats, and images above 60 million pixels.
- Reads JPEG, PNG, WebP, MPO, and HEIF/HEIC images; **pillow-heif** adds HEIF support.
- Applies EXIF rotation, converts images to RGB, and resizes them to a maximum 1,600-pixel edge.
- Re-encodes images as WebP at quality 80 before saving.

## Logging
Everything is written to stdout, so Docker collects it, and also to files in the `logs/` directory of the project (gitignored, created automatically):

```bash
docker compose logs -f web          # follow the application
docker compose logs --since 1h web  # last hour
docker compose logs web | grep ERROR
tail -f logs/app.log                # the same, from the files
```

| File | Content |
| --- | --- |
| `logs/app.log` | Application log: errors, warnings and events |
| `logs/gunicorn-access.log` | One line per request |
| `logs/gunicorn-error.log` | Gunicorn start, stop and worker messages |
| `logs/gr8base-backup.log` | Deploy, backup and restore runs (written by the scripts) |

- **Rotation:** each `.log` file in `logs/` is rotated at 10 MB and keeps 3 old copies (`app.log.1` to `app.log.3`). Container logs are limited the same way (`x-logging` in `docker-compose.yml`). `gr8base-backup.log` is written by shell scripts and not rotated; it only grows by a few lines per deploy.
- **Level:** `DJANGO_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING` or `ERROR`). Production defaults to `INFO`, development to `DEBUG`. Set it in `.env` and run `docker compose up -d` to apply.
- **Errors:** unhandled exceptions are logged with a traceback (`django.request`). Django's default would drop them when `DEBUG` is off, so `LOGGING` in `gr8base/settings.py` sends them to the console and to `app.log`.
- **Requests:** Gunicorn writes one access line per request (configured in `gunicorn.conf.py`). Django logs only 5xx errors, so nothing is duplicated.
- **Events** (at `INFO`): crag created, updated and deleted; photos uploaded and deleted; user signed up. Rejected uploads are logged as `WARNING` with the reason (`too large`, `format`, `too many pixels`, `unreadable`).
- **Privacy:** events contain IDs only (`crag created id=12 user=3 status=DRAFT`). No names, e-mail addresses or file names; keep it that way when adding new log calls.
- **Single worker:** the size-based rotation assumes Gunicorn's single worker process. If `workers` is raised, use a rotation that is safe across processes (for example `logrotate` on the host).
- **Not covered:** `$BACKUP_DIR/deploy.log` (read by `restore.sh`) stays next to the backups, see [scripts/README.md](../scripts/README.md). There is no alerting; errors are found by reading the logs.

## No service worker (offline copies removed)

Until November 2026 a service worker kept the pages a visitor opened, for reading without signal. It was removed completely:

- Pages are personalised (private review threads, change requests, moderator tools), and the copies could stay on a shared device after the session ended.
- The site is for choosing a crag, usually with signal, and the copies saved no data: pages were always loaded from the network first. Less data comes from the browser's normal cache instead: CSS and JS have hashed names and photos are served as immutable (WhiteNoise, Caddy), plus thumbnails and compression.

There is no `/sw.js` and no registration script any more. A browser that still has the old worker keeps it until its site data is cleared (only one device had it). A service worker will be added again, written fresh, for push notifications (number badge on the app icon).
