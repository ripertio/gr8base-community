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


class NoServiceWorkerTests(TestCase):
    """No offline copies; without push keys no worker at all (crags/push.py has the push one).

    The old offline worker's copies could keep private content (review threads,
    change requests) on a shared device.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from crags.models import Area, Crag

        cls.user = get_user_model().objects.create_user("owner", "o@example.com", "pw-owner-123")
        cls.crag = Crag.objects.create(
            name="Some crag", area=Area.objects.create(name="Area"),
            created_by=cls.user, status=Crag.Status.PUBLISHED,
        )

    def get(self, url, **kwargs):
        return self.client.get(url, secure=True, **kwargs)

    def test_worker_and_offline_page_are_gone(self):
        self.assertEqual(self.get("/sw.js").status_code, 404)
        self.assertEqual(self.get("/offline/").status_code, 404)

    def test_no_page_registers_a_worker_or_is_marked_for_copies(self):
        self.client.force_login(self.user)
        urls = [
            reverse("home"), reverse("crags:list"),
            reverse("crags:detail", args=[self.crag.pk]),
            reverse("docs"), reverse("doc_page", args=["privacy"]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "serviceWorker")
                self.assertNotIn("X-Offline-Cache", response)

    def test_privacy_page_no_longer_mentions_offline_copies(self):
        self.assertNotContains(self.get(reverse("doc_page", args=["privacy"])), "Offline copies")


class WebManifestTests(TestCase):
    """The site is installable as an app (gr8base/views.py web_manifest)."""

    def test_manifest_names_icons_and_display(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual((data["name"], data["short_name"], data["display"]), ("gr8base community", "gr8base", "standalone"))
        self.assertEqual(data["start_url"], "/")
        sizes = {(icon["sizes"], icon.get("purpose", "any")) for icon in data["icons"]}
        self.assertEqual(sizes, {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")})

    def test_icon_files_exist_in_the_right_sizes(self):
        from PIL import Image
        for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512),
                           ("apple-touch-icon.png", 180), ("favicon-32.png", 32)):
            with Image.open(settings.BASE_DIR / "static" / "icons" / name) as image:
                self.assertEqual(image.size, (size, size), name)

    def test_every_page_links_manifest_and_icons(self):
        response = self.client.get(reverse("crags:list"))
        self.assertContains(response, '<link rel="manifest" href="/manifest.webmanifest">')
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, '<meta name="theme-color" content="#0172ad">')

    def test_manifest_is_not_counted_as_a_visit(self):
        from stats.models import DailyHits
        self.client.cookies["cookie_consent"] = "yes"
        self.client.get("/manifest.webmanifest")
        self.assertFalse(DailyHits.objects.exists())


class FaqNavigationTests(TestCase):
    """"FAQ" (the /docs/ page) replaces "Help"; Stats moved from the header into it."""

    def test_header_has_faq_and_no_stats(self):
        content = self.client.get(reverse("crags:list")).content.decode()
        nav = content[content.index('<ul class="nav-links">'):content.index("</nav>")]
        self.assertIn(f'<a href="{reverse("docs")}">FAQ</a>', nav)
        self.assertNotIn(reverse("stats:index"), nav)
        self.assertNotIn(">Help<", nav)

    def test_faq_page_links_to_statistics(self):
        response = self.client.get(reverse("docs"))
        self.assertContains(response, f'<a href="{reverse("stats:index")}">Site statistics</a>', html=True)
        self.assertContains(response, "FAQ – gr8base community")
        self.assertContains(response, ">Frequently asked questions</h1>")
        self.assertContains(response, "Useful information")

    def test_footer_links_to_faq(self):
        content = self.client.get(reverse("crags:list")).content.decode()
        footer = content[content.index('<footer class="container site-footer">'):]
        self.assertIn(f'<a href="{reverse("docs")}">FAQ</a>', footer)
