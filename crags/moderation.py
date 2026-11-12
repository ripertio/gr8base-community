from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, F, IntegerField, Value, When
from django.shortcuts import render
from django.utils.http import urlencode

from .models import Crag

# Removed crags are never listed here (they only exist in the admin).
STATUSES = [(value, label) for value, label in Crag.Status.choices if value != Crag.Status.REMOVED]


def moderator_required(view):
    """Staff (they can edit any crag) and publishers may open the moderation pages.

    Anonymous users go to the login page, everyone else gets a 403. Actions that change
    a crag's status must still check ``crags.can_publish_crag`` themselves.
    """

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_staff or user.has_perm("crags.can_publish_crag")):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@moderator_required
def queue(request):
    """Crags except removed ones; the status chips filter the list.

    Without a ``status`` parameter Pending is preselected (the review queue);
    an empty ``?status=`` means no filter, i.e. all statuses.
    """
    valid = {value for value, _ in STATUSES}
    if "status" in request.GET:
        selected = [s for s in request.GET.getlist("status") if s in valid]
    else:
        selected = [Crag.Status.PENDING.value]

    crags = (
        Crag.objects.select_related("area", "created_by")
        .annotate(photo_count=Count("photos"))
        .order_by(
            Case(
                When(status=Crag.Status.PENDING, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            F("submitted_at").asc(nulls_last=True),
            "pk",
        )
    )
    if selected:
        crags = crags.filter(status__in=selected)

    counts = dict(Crag.objects.order_by().values_list("status").annotate(n=Count("pk")))
    chips = []
    for value, label in STATUSES:
        toggled = [s for s in selected if s != value]
        if value not in selected:
            toggled.append(value)
        chips.append(
            {
                "label": label,
                "count": counts.get(value, 0),
                "selected": value in selected,
                # "status=" (empty) keeps the page from falling back to the default
                "query": urlencode([("status", s) for s in toggled] or [("status", "")]),
            }
        )
    return render(
        request,
        "crags/moderation_queue.html",
        {
            "crags": crags,
            "chips": chips,
            "filtered": bool(selected),
            "show_all_query": urlencode([("status", "")]),
        },
    )
