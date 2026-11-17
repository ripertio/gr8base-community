"""Gunicorn settings (picked up automatically from the working directory).

Logs go to the console (so `docker compose logs web` works) and to rotated
files in logs/ (untracked in git). Gunicorn runs a single worker process here,
so the size-based rotation does not race between processes; revisit it if
`workers` is ever raised.

That one process has several threads, so a slow request (e.g. converting a
batch of uploaded photos) no longer makes every other visitor wait. Threads
share the log handlers, which are thread-safe, so rotation stays correct.
"""

import logging
import re
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

bind = "0.0.0.0:8000"
loglevel = "info"

# Behind Caddy and the Cloudflare tunnel every connection comes from Caddy, so log
# the visitor's address from the header Cloudflare sets (it overwrites any value a
# client sends; the app is only reachable through the tunnel). "-" when absent.
access_log_format = (
    '%({cf-connecting-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
)

workers = 1
worker_class = "gthread"
threads = 4

class DropHealthyChecks(logging.Filter):
    """Skip access lines for successful /healthz/ probes (~90% of the log).

    Failed checks (non-200) are still logged.
    """

    _probe = re.compile(r'"(?:GET|HEAD) /healthz/\S* HTTP/[\d.]+" 200 ')

    def filter(self, record):
        return not self._probe.search(record.getMessage())


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
    "filters": {"drop_healthy_checks": {"()": DropHealthyChecks}},
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
            "filters": ["drop_healthy_checks"],
            "propagate": False,
            "qualname": "gunicorn.access",
        },
    },
}
