import copy
import io
import logging
import logging.config
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
        self.assertGreaterEqual(logging.getLevelName(django_request["level"]), logging.WARNING)

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
