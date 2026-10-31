from datetime import datetime, time, timedelta

from django.db.models import F
from django.utils import timezone

from .models import DailyHits

COOKIE = "seen_today"
SKIPPED_PREFIXES = ("/static/", "/media/", "/admin/", "/healthz/", "/stats/")


class UniqueVisitorMiddleware:
    """Count each browser at most once per day.

    A cookie holding today's date that expires at midnight marks a browser as
    counted. Nothing identifying is stored on the server, only the counter.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method != "GET"
            or response.status_code != 200
            or request.path.startswith(SKIPPED_PREFIXES)
            or request.user.is_staff
        ):
            return response

        now = timezone.localtime()
        today = now.date().isoformat()
        if request.COOKIES.get(COOKIE) == today:
            return response

        hits, _ = DailyHits.objects.get_or_create(date=now.date())
        DailyHits.objects.filter(pk=hits.pk).update(count=F("count") + 1)

        midnight = timezone.make_aware(
            datetime.combine(now.date() + timedelta(days=1), time.min)
        )
        response.set_cookie(
            COOKIE,
            today,
            max_age=int((midnight - now).total_seconds()),
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
        return response
