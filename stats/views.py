from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from crags.models import Crag

from .models import DailyHits

WIDTH, HEIGHT = 600, 220
LEFT, RIGHT, TOP, BOTTOM = 48, 12, 10, 44


def cumulative(dates, start, end):
    """Running total per day from `start` to `end` (inclusive)."""
    per_day = {}
    before = 0
    for d in dates:
        if d < start:
            before += 1
        else:
            per_day[d] = per_day.get(d, 0) + 1
    total, series = before, []
    for i in range((end - start).days + 1):
        day = start + timedelta(days=i)
        total += per_day.get(day, 0)
        series.append((day, total))
    return series


def chart(series, y_label, bars=False):
    """Turn [(date, value)] into SVG coordinates for the template."""
    top = max((v for _, v in series), default=0) or 1
    n = len(series)
    plot_w = WIDTH - LEFT - RIGHT
    plot_h = HEIGHT - TOP - BOTTOM
    base = TOP + plot_h
    step = plot_w / max(n - 1, 1)
    points = [
        (LEFT + i * step, base - (v / top) * plot_h) for i, (_, v) in enumerate(series)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    mid = n // 2
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "left": LEFT,
        "right": WIDTH - RIGHT,
        "base": base,
        "y_label": y_label,
        "y_label_y": TOP + plot_h / 2,
        "x_label_x": LEFT + plot_w / 2,
        "x_label_y": HEIGHT - 6,
        "tick_y": base + 16,
        "latest": series[-1][1] if series else 0,
        "y_ticks": [
            {"y": f"{base - f * plot_h:.1f}", "value": round(top * f)}
            for f in (0, 0.5, 1)
        ],
        "x_ticks": [
            {"x": f"{points[i][0]:.1f}", "day": series[i][0], "anchor": anchor}
            for i, anchor in ((0, "start"), (mid, "middle"), (n - 1, "end"))
        ] if series else [],
        "line": line,
        "area": f"{LEFT},{base} {line} {points[-1][0]:.1f},{base}" if points else "",
        "bars": [
            {"x": f"{x - step * 0.4:.1f}", "y": f"{y:.1f}",
             "w": f"{max(step * 0.8, 1):.1f}", "h": f"{base - y:.1f}"}
            for x, y in points
        ] if bars else [],
    }


MEDALS = ("#d4af37", "#a8a9ad", "#cd7f32")  # gold, silver, bronze
BAR_LEFT, BAR_H, BAR_GAP = 120, 28, 14


def top_contributors(limit=3):
    """Users who created the most crags.

    Only users who made their profile public are named; everyone else is
    shown as "Anonymous".
    """
    User = get_user_model()
    users = User.objects.annotate(n_crags=Count("crags")).order_by("id")
    scored = sorted(((u, u.n_crags) for u in users), key=lambda t: -t[1])
    scored = [t for t in scored if t[1] > 0][:limit]
    top = scored[0][1] if scored else 1
    plot_w = WIDTH - BAR_LEFT - 48
    bars = []
    for i, (u, score) in enumerate(scored):
        y = TOP + i * (BAR_H + BAR_GAP)
        bars.append({
            "name": u.username if u.profile_public else "Anonymous",
            "score": score,
            "y": y,
            "mid": y + BAR_H / 2,
            "w": max(score / top * plot_w, 2),
            "medal": MEDALS[i],
            "rank": i + 1,
        })
    return {
        "width": WIDTH,
        "height": TOP * 2 + max(len(bars), 1) * (BAR_H + BAR_GAP),
        "left": BAR_LEFT,
        "bars": bars,
    }


@user_passes_test(lambda u: u.is_active and u.is_staff, login_url="account_login")
def stats(request):
    today = timezone.localdate()
    User = get_user_model()

    user_dates = [d.date() for d in User.objects.values_list("date_joined", flat=True)]
    crag_dates = [d.date() for d in Crag.objects.values_list("created_at", flat=True)]
    first = min(user_dates + crag_dates + [today - timedelta(days=29)])

    hits = dict(DailyHits.objects.values_list("date", "count"))
    visitors = [
        (first + timedelta(days=i), hits.get(first + timedelta(days=i), 0))
        for i in range((today - first).days + 1)
    ]

    return render(request, "stats/stats.html", {
        "visitors": chart(visitors, "Visitors", bars=True),
        "visitors_today": hits.get(today, 0),
        "users": chart(cumulative(user_dates, first, today), "Users"),
        "crags": chart(cumulative(crag_dates, first, today), "Crags"),
        "contributors": top_contributors(),
    })
