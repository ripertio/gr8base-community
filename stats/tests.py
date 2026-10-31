from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .views import cumulative


class CumulativeTests(TestCase):
    def test_running_total_includes_earlier_items(self):
        dates = [date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 3)]
        series = cumulative(dates, date(2026, 1, 2), date(2026, 1, 4))
        self.assertEqual([v for _, v in series], [1, 3, 3])


class StatsViewTests(TestCase):
    def test_staff_only(self):
        User = get_user_model()
        self.assertEqual(self.client.get(reverse("stats:index")).status_code, 302)
        User.objects.create_user("u", "u@example.com", "pw")
        self.client.login(username="u", password="pw")
        self.assertEqual(self.client.get(reverse("stats:index")).status_code, 302)
        User.objects.create_user("s", "s@example.com", "pw", is_staff=True)
        self.client.login(username="s", password="pw")
        self.assertEqual(self.client.get(reverse("stats:index")).status_code, 200)
