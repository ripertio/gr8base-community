import copy
import io
import logging
import logging.config
import logging.handlers
import os
import runpy
from unittest import mock

from django.conf import settings
from django.db import OperationalError
from django.test import Client, TestCase
from django.urls import reverse


class HealthzTests(TestCase):
    def test_ok(self):
        response = self.client.get(reverse("healthz"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_db_failure_returns_503(self):
        with mock.patch("gr8base.views.connection.cursor", side_effect=OperationalError):
            response = self.client.get(reverse("healthz"), secure=True)
        self.assertEqual(response.status_code, 503)


class LoggingConfigTests(TestCase):
    def test_console_handler_writes_to_stdout_without_debug_filter(self):
        handler = settings.LOGGING["handlers"]["console"]
        self.assertEqual(handler["class"], "logging.StreamHandler")
        self.assertEqual(handler["stream"], "ext://sys.stdout")
        self.assertNotIn("require_debug_true", handler.get("filters", []))

    def test_root_and_django_loggers_use_console(self):
        self.assertIn("console", settings.LOGGING["root"]["handlers"])
        self.assertIn("console", settings.LOGGING["loggers"]["django"]["handlers"])
        django_request = settings.LOGGING["loggers"]["django.request"]
        self.assertGreaterEqual(logging.getLevelName(django_request["level"]), logging.ERROR)

    def test_log_level_is_valid(self):
        level = settings.LOGGING["root"]["level"]
        self.assertIsInstance(logging.getLevelName(level), int)

    def test_unhandled_exception_is_written_to_console(self):
        stream = io.StringIO()
        config = copy.deepcopy(settings.LOGGING)
        config["handlers"]["console"]["stream"] = stream
        logging.config.dictConfig(config)
        self.addCleanup(logging.config.dictConfig, settings.LOGGING)

        client = Client(raise_request_exception=False)
        with mock.patch("gr8base.views.render", side_effect=RuntimeError("boom")):
            response = client.get(reverse("docs"), secure=True)

        self.assertEqual(response.status_code, 500)
        output = stream.getvalue()
        self.assertIn("boom", output)
        self.assertIn("Traceback", output)

    def test_app_log_file_is_rotating_and_lives_in_logs_dir(self):
        self.assertEqual(settings.LOG_DIR, settings.BASE_DIR / "logs")
        handler = settings.LOGGING["handlers"]["file"]
        self.assertEqual(handler["class"], "logging.handlers.RotatingFileHandler")
        self.assertGreater(handler["maxBytes"], 0)
        self.assertGreater(handler["backupCount"], 0)
        self.assertIn("file", settings.LOGGING["root"]["handlers"])
        self.assertIn("file", settings.LOGGING["loggers"]["django.request"]["handlers"])
        # the test runner must not write into the real logs/ directory
        self.assertEqual(handler["filename"], os.devnull)

    def test_gunicorn_writes_rotating_files_into_logs_dir(self):
        conf = runpy.run_path(str(settings.BASE_DIR / "gunicorn.conf.py"))
        config = conf["logconfig_dict"]
        for name in ("gunicorn.access", "gunicorn.error"):
            self.assertIn("file_" + name.split(".")[1], config["loggers"][name]["handlers"])
        for key in ("file_access", "file_error"):
            handler = config["handlers"][key]
            self.assertEqual(handler["class"], "logging.handlers.RotatingFileHandler")
            self.assertEqual(os.path.dirname(handler["filename"]), str(settings.LOG_DIR))
        # the console handlers stay, so `docker compose logs` keeps working
        self.assertIn("console", config["loggers"]["gunicorn.error"]["handlers"])
        self.assertIn("access_console", config["loggers"]["gunicorn.access"]["handlers"])
