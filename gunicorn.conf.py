"""Gunicorn settings (picked up automatically from the working directory).

Logs go to the console (so `docker compose logs web` works) and to rotated
files in logs/ (untracked in git). Gunicorn runs a single worker process here,
so the size-based rotation does not race between processes; revisit it if
`workers` is ever raised.

That one process has several threads, so a slow request (e.g. converting a
batch of uploaded photos) no longer makes every other visitor wait. Threads
share the log handlers, which are thread-safe, so rotation stays correct.
"""

from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

bind = "0.0.0.0:8000"
loglevel = "info"

workers = 1
worker_class = "gthread"
threads = 4

_file = {
    "class": "logging.handlers.RotatingFileHandler",
    "maxBytes": 10 * 1024 * 1024,
    "backupCount": 3,
    "encoding": "utf-8",
}

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter",
        },
        "access": {"format": "%(message)s", "class": "logging.Formatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "generic",
            "stream": "ext://sys.stderr",
        },
        "access_console": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
        "file_error": {**_file, "filename": str(LOG_DIR / "gunicorn-error.log"), "formatter": "generic"},
        "file_access": {**_file, "filename": str(LOG_DIR / "gunicorn-access.log"), "formatter": "access"},
    },
    "loggers": {
        "gunicorn.error": {
            "level": "INFO",
            "handlers": ["console", "file_error"],
            "propagate": False,
            "qualname": "gunicorn.error",
        },
        "gunicorn.access": {
            "level": "INFO",
            "handlers": ["access_console", "file_access"],
            "propagate": False,
            "qualname": "gunicorn.access",
        },
    },
}
