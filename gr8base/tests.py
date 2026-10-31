from unittest import mock

from django.db import OperationalError
from django.test import TestCase
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
