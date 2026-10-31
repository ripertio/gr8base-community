from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from crags.models import Area, Crag

from .models import DailyHits
from .views import cumulative, top_contributors
from crags.models import Area, Crag

from .models import DailyHits
from .views import cumulative, top_contributors


class CumulativeTests(TestCase):
    def test_running_total_includes_earlier_items(self):
        dates = [date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 3)]
        series = cumulative(dates, date(2026, 1, 2), date(2026, 1, 4))
        self.assertEqual([v for _, v in series], [1, 3, 3])


class StatsViewTests(TestCase):
    def test_public_sees_only_users_and_crags(self):
        r = self.client.get(reverse("stats:index"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Users over time")
        self.assertContains(r, "Crags over time")
        self.assertNotContains(r, "Daily visitors")
        self.assertNotContains(r, "Crag Kings")

    def test_regular_user_sees_no_admin_charts(self):
        get_user_model().objects.create_user("u", "u@example.com", "pw")
    def test_public_sees_only_users_and_crags(self):
        r = self.client.get(reverse("stats:index"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Users over time")
        self.assertContains(r, "Crags over time")
        self.assertNotContains(r, "Daily visitors")
        self.assertNotContains(r, "Crag Kings")

    def test_regular_user_sees_no_admin_charts(self):
        get_user_model().objects.create_user("u", "u@example.com", "pw")
        self.client.login(username="u", password="pw")
        self.assertNotContains(self.client.get(reverse("stats:index")), "Daily visitors")

    def test_staff_sees_all_charts(self):
        get_user_model().objects.create_user("s", "s@example.com", "pw", is_staff=True)
        self.client.login(username="s", password="pw")
        r = self.client.get(reverse("stats:index"))
        self.assertContains(r, "Daily visitors")
        self.assertContains(r, "Crag Kings")


class TopContributorsTests(TestCase):
    def test_ranks_and_hides_private_names(self):
        User = get_user_model()
        a = User.objects.create_user("alice", "a@example.com", "pw", profile_public=True)
        b = User.objects.create_user("bob", "b@example.com", "pw")
        area = Area.objects.create(name="Allgau")
        for i in range(2):
            Crag.objects.create(name=f"A{i}", area=area, created_by=a)
        Crag.objects.create(name="B", area=area, created_by=b)
        bars = top_contributors()["bars"]
        self.assertEqual([x["name"] for x in bars], ["alice", "Anonymous"])
        self.assertEqual([x["score"] for x in bars], [2, 1])


class UniqueVisitorTests(TestCase):
    def setUp(self):
        self.client.cookies["cookie_consent"] = "yes"

    def test_nothing_counted_without_consent(self):
        self.client.cookies["cookie_consent"] = "no"
        self.client.get("/")
        self.assertFalse(DailyHits.objects.exists())

    def test_reload_counts_once_per_browser(self):
        self.client.get("/")
        self.client.get("/")
        self.assertEqual(DailyHits.objects.get().count, 1)
        self.client.cookies.clear()
        self.client.cookies["cookie_consent"] = "yes"
        self.client.get("/")
        self.assertEqual(DailyHits.objects.get().count, 2)

    def test_admins_and_skipped_paths_not_counted(self):
        self.client.get("/healthz/")
        self.assertFalse(DailyHits.objects.exists())
        get_user_model().objects.create_superuser("a", "a@example.com", "pw")
        self.client.login(username="a", password="pw")
        self.client.get("/")
        self.assertFalse(DailyHits.objects.exists())

    def test_moderators_are_counted(self):
        get_user_model().objects.create_user("m", "m@example.com", "pw", is_staff=True)
        self.client.login(username="m", password="pw")
        self.client.get("/")
        hits = DailyHits.objects.get()
        self.assertEqual((hits.count, hits.logged_in_count), (1, 1))

    def test_login_after_anonymous_visit_counts_as_member_once(self):
        get_user_model().objects.create_user("u", "u@example.com", "pw")
        self.client.get("/")
        self.client.login(username="u", password="pw")
        self.client.get("/")
        self.client.get("/")
        hits = DailyHits.objects.get()
        self.assertEqual((hits.count, hits.logged_in_count), (1, 1))


class CookieBannerTests(TestCase):
    def test_banner_shown_until_choice_made(self):
        self.assertContains(self.client.get("/"), "cookie-banner")
        self.client.post(reverse("cookie_consent"), {"choice": "decline"})
        self.assertNotContains(self.client.get("/"), "cookie-banner")

    def test_accept_sets_cookie_and_redirects_safely(self):
        r = self.client.post(
            reverse("cookie_consent"), {"choice": "accept", "next": "https://evil.example/"}
        )
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        self.assertEqual(r.cookies["cookie_consent"].value, "yes")

    def test_decline_clears_counter_cookie_and_reset_asks_again(self):
        self.client.cookies["seen_today"] = "2026-01-01"
        r = self.client.post(reverse("cookie_consent"), {"choice": "decline"})
        self.assertEqual(r.cookies["seen_today"].value, "")
        r = self.client.post(reverse("cookie_consent"), {"choice": "reset"})
        self.assertEqual(r.cookies["cookie_consent"].value, "")
