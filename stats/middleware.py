from datetime import datetime, time, timedelta

from django.db.models import F
from django.utils import timezone

from .models import DailyHits

COOKIE = "seen_today"
CONSENT_COOKIE = "cookie_consent"
SKIPPED_PREFIXES = ("/static/", "/media/", "/admin/", "/healthz/", "/stats/", "/cookies/")


class UniqueVisitorMiddleware:
    """Count each browser at most once per day.

    A cookie holding today's date that expires at midnight marks a browser as
    counted, and whether it was seen logged in. Only runs with the visitor's
    consent (the `cookie_consent` cookie). Nothing identifying is stored on the server, only the counter.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method != "GET"
            or response.status_code != 200
            or request.path.startswith(SKIPPED_PREFIXES)
            or request.user.is_superuser
            or request.COOKIES.get(CONSENT_COOKIE) != "yes"
        ):
            return response

        now = timezone.localtime()
        today = now.date().isoformat()
        # cookie is "<date>" for anonymous browsers, "<date>:u" once counted as logged in
        seen = request.COOKIES.get(COOKIE, "")
        seen_date, _, seen_user = seen.partition(":")
        is_user = request.user.is_authenticated
        counted_today = seen_date == today
        if counted_today and (seen_user or not is_user):
            return response

        hits, _ = DailyHits.objects.get_or_create(date=now.date())
        updates = {}
        if not counted_today:
            updates["count"] = F("count") + 1
        if is_user:
            updates["logged_in_count"] = F("logged_in_count") + 1
        DailyHits.objects.filter(pk=hits.pk).update(**updates)

        midnight = timezone.make_aware(
            datetime.combine(now.date() + timedelta(days=1), time.min)
        )
        response.set_cookie(
            COOKIE,
            f"{today}:u" if is_user else today,
            max_age=int((midnight - now).total_seconds()),
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
        return response
