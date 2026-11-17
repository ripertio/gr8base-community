from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, F, IntegerField, OuterRef, Subquery, Value, When
from django.shortcuts import render
from django.utils.http import urlencode

from .models import ChangeRequest, Crag, ReviewMessage

# Removed crags are never listed here (they only exist in the admin).
STATUSES = [(value, label) for value, label in Crag.Status.choices if value != Crag.Status.REMOVED]


def with_last_review_message(crags):
    """Annotate last_review_kind and last_review_author (the newest review entry)."""
    last = ReviewMessage.objects.filter(crag=OuterRef("pk")).order_by("-created_at", "-pk")
    return crags.annotate(
        last_review_kind=Subquery(last.values("kind")[:1]),
        last_review_author=Subquery(last.values("author_id")[:1]),
    )


def awaiting_answer(crags):
    """Crags under review whose submitter wrote the last message: a moderator should answer."""
    return with_last_review_message(crags).filter(
        status__in=ReviewMessage.OPEN_STATUSES,
        last_review_kind=ReviewMessage.Kind.MESSAGE,
        last_review_author=F("created_by"),
    )


def open_task_count():
    """Crags waiting for review (the counter next to "Moderation").

    Replies in a review are not counted here: the moderators involved already
    get a personal notification for them, which would count the same reply
    twice. The queue still lists them under "Waiting for your answer".
    """
    return Crag.objects.filter(status=Crag.Status.PENDING).count()


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

    crags = with_last_review_message(
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
            # shown above the list whatever the filter: the submitter is waiting
            "awaiting_answer": awaiting_answer(
                Crag.objects.select_related("created_by")
            ).order_by("name"),
            # shown above the list whatever the filter
            "open_change_requests": ChangeRequest.objects.filter(
                status=ChangeRequest.Status.OPEN
            ).exclude(crag__status=Crag.Status.REMOVED).select_related("crag", "requester"),
            "chips": chips,
            "filtered": bool(selected),
            "show_all_query": urlencode([("status", "")]),
        },
    )
