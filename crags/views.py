import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from gr8base.offline import offline_cacheable

from .forms import BulkPhotoForm, CragForm, coordinates_from_photos, process_image
from .models import (
    Area, Crag, CragComment, CragRating, Feature, InvalidTransition, Notification, Photo,
    ReviewMessage,
)
from .change_requests import can_handle, can_suggest, requests_for_crag_page
from .notifications import (
    CHANNELS, can_moderate, notify_owner, notify_review_message, types_for, wants,
)

logger = logging.getLogger(__name__)

MAX_PHOTOS_PER_CRAG = 8
SUGGESTIONS_MAX_AGE = 300  # seconds; new crags show up in suggestions after this
MAX_FILES_PER_UPLOAD = 8

PUBLISH_PERM = "crags.can_publish_crag"


def return_target(request):
    """The page to go back to after an action, e.g. the moderation queue, or "".

    Passed along as ``next`` (query string or hidden field); only local URLs count.
    """
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return ""


def with_query(url, params):
    """url with the non-empty params as a query string."""
    params = {key: value for key, value in params.items() if value}
    return f"{url}?{urlencode(params)}" if params else url


def with_next(url, target):
    """Append ``?next=target`` to url, so the following page can return there."""
    return f"{url}?{urlencode({'next': target})}" if target else url


def detail_url(crag, request):
    """The crag page, keeping the return target (used when an action failed)."""
    return with_next(reverse("crags:detail", args=[crag.pk]), return_target(request))


def can_see_review(user, crag):
    """The review thread is private: the crag's submitter and moderators."""
    return user.is_authenticated and (crag.created_by_id == user.id or can_moderate(user))


def review_context(user, crag):
    """The review thread for the crag page, or None if the user may not see it."""
    if not can_see_review(user, crag):
        return None
    entries = list(crag.review_messages.select_related("author"))
    can_reply = crag.status in ReviewMessage.OPEN_STATUSES
    if not entries and not can_reply:
        return None
    return {
        "entries": entries,
        "can_reply": can_reply,
        "is_submitter": crag.created_by_id == user.id,
        "max_length": ReviewMessage.MAX_LENGTH,
    }


def report_photo_coordinates(request, crag):
    """Tell the user to check prefilled coordinates; log ids only, never the position."""
    messages.warning(
        request,
        "The crag coordinates were taken from the location of a photo. "
        "Please check them on the map and correct them if needed.",
    )
    logger.info("crag coordinates from photo crag=%s user=%s", crag.pk, request.user.pk)


def can_publish_now(user, crag):
    """Publish buttons: the user may publish and the crag is not published yet."""
    return (
        user.has_perm(PUBLISH_PERM)
        and Crag.Status.PUBLISHED in crag.ALLOWED_TRANSITIONS[crag.status]
    )


def can_return_now(user, crag):
    """"Needs changes" button: the user may publish/return and the move is allowed."""
    return (
        user.has_perm(PUBLISH_PERM)
        and Crag.Status.NEEDS_CHANGES in crag.ALLOWED_TRANSITIONS[crag.status]
    )


def can_reject_now(user, crag):
    """"Reject" button: the user may publish/return/reject and the move is allowed."""
    return (
        user.has_perm(PUBLISH_PERM)
        and Crag.Status.REJECTED in crag.ALLOWED_TRANSITIONS[crag.status]
    )


def reason_error(reason):
    if len((reason or "").strip()) < Crag.MIN_REASON_LENGTH:
        return f"Please give a reason of at least {Crag.MIN_REASON_LENGTH} characters."
    return None


def visible_crags(user):
    """Who may SEE which crags."""
    qs = Crag.objects.select_related("area")
    if user.is_staff:
        return qs
    if user.is_authenticated:
        return qs.filter(Q(status__in=Crag.PUBLIC_STATUSES) | Q(created_by=user))
    return qs.public()


def editable_crags(user):
    """Who may CHANGE which crags."""
    if user.is_staff:
        return Crag.objects.all()
    return Crag.objects.filter(created_by=user)


def removable_crags(user):
    """Who may REMOVE (soft-delete) which crags: owners and users with the permission."""
    if user.has_perm("crags.can_remove_crag"):
        return Crag.objects.all()
    return Crag.objects.filter(created_by=user)


def unique(values):
    """Non-empty values in their first order, without repeats."""
    return list(dict.fromkeys(value for value in values if value))


AGE_FIELDS = {
    "babies": ("Babies", "rating_babies"),
    "ages_2_4": ("Ages 2–4", "rating_ages_2_4"),
    "ages_5_plus": ("Ages 5+", "rating_ages_5_plus"),
}
APPROACH_CHOICES = (5, 10, 15, 20, 30)
# ?sort= values for the crag list; the first one is the default.
# updated_at is set on creation too, so a new crag counts as just modified.
SORT_CHOICES = {
    "updated": ("Last updated: newest first", ("-updated_at", "-pk")),
    "updated_oldest": ("Last updated: oldest first", ("updated_at", "pk")),
    "name": ("Name: A–Z", ("name", "pk")),
}
DEFAULT_SORT = "updated"
STROLLER_SLUG = "stroller_friendly"


@offline_cacheable
def crag_list(request):
    crags = Crag.objects.select_related("area").public()
    get = request.GET
    query = get.get("q", "").strip()
    # area and orientation may be given several times (?area=A&area=B)
    area_names = unique(get.getlist("area"))
    # one minimum star rating per age group, e.g. ?rating_babies=4&rating_ages_5_plus=3
    min_ratings = {
        field: int(get[field])
        for _, field in AGE_FIELDS.values()
        if get.get(field, "").isdecimal() and 1 <= int(get[field]) <= 5
    }
    orientations = [
        value for value in unique(get.getlist("orientation"))
        if value in Crag.Orientation.values
    ]
    max_approach = get.get("max_approach", "")
    sort = get.get("sort", "")
    if sort not in SORT_CHOICES:
        sort = DEFAULT_SORT
    stroller_approach = get.get("stroller_approach") == "1"
    stroller_base = get.get("stroller_base") == "1"

    hazards = Feature.objects.exclude(slug=STROLLER_SLUG).order_by("label")
    hazard_slugs = {h.slug for h in hazards}
    avoid = [slug for slug in get.getlist("avoid") if slug in hazard_slugs]

    if area_names:
        known = set(Area.objects.filter(name__in=area_names).values_list("name", flat=True))
        area_names = [name for name in area_names if name in known]
    if not (max_approach.isdecimal() and int(max_approach) in APPROACH_CHOICES):
        max_approach = ""

    if query:
        crags = crags.filter(
            Q(name__icontains=query)
            | Q(area__name__icontains=query)
            | Q(description__icontains=query)
        )

    if area_names:  # any of the areas
        crags = crags.filter(area__name__in=area_names)

    # Every age group with a minimum must reach it (a family with a baby and a
    # 6-year-old needs a crag that is good for both).
    for field, stars in min_ratings.items():
        crags = crags.filter(**{f"{field}__gte": stars})

    if orientations:  # any of the aspects
        crags = crags.filter(orientation__in=orientations)

    if max_approach:
        crags = crags.filter(approach_minutes__lte=max_approach)

    if stroller_approach:
        crags = crags.filter(approach_features__slug=STROLLER_SLUG)

    if stroller_base:
        crags = crags.filter(base_features__slug=STROLLER_SLUG)

    # Known hazards only: crags without any assessment are not excluded.
    for slug in avoid:
        crags = crags.exclude(
            Q(approach_features__slug=slug) | Q(base_features__slug=slug)
        )

    crags = list(crags.distinct().order_by(*SORT_CHOICES[sort][1]))
    # Community averages in one query; set on the crags so the template stays simple
    averages = {
        row["crag_id"]: row
        for row in CragRating.objects.filter(crag__in=crags)
        .values("crag_id")
        .annotate(
            babies=Avg("rating_babies"),
            ages_2_4=Avg("rating_ages_2_4"),
            ages_5_plus=Avg("rating_ages_5_plus"),
        )
    }
    comment_counts = dict(
        CragComment.objects.filter(crag__in=crags)
        .values_list("crag_id")
        .annotate(n=Count("id"))
    )
    # First photo of each crag (same order as crag.photos.first()), one query in total
    cover_photos = {
        photo.crag_id: photo
        for photo in Photo.objects.filter(crag__in=crags)
        .order_by("crag_id", "created_at", "pk")
        .distinct("crag_id")
    }
    for crag in crags:
        crag.community = averages.get(crag.pk, {})
        crag.comment_count = comment_counts.get(crag.pk, 0)
        crag.cover_photo = cover_photos.get(crag.pk)
    areas = list(
        Area.objects.filter(crags__status__in=Crag.PUBLIC_STATUSES)
        .distinct()
        .order_by("name")
    )

    active_filters = (
        bool(area_names)
        + len(min_ratings)
        + bool(orientations)
        + bool(max_approach)
        + stroller_approach
        + stroller_base
        + len(avoid)
    )

    context = {
        "crags": crags,
        "areas": areas,
        "query": query,
        "selected_areas": area_names,
        # in dropdown order, for the closed dropdown ("Allgäu, Zillertal")
        "selected_area_labels": [area.name for area in areas if area.name in area_names],
        "selected_orientations": orientations,
        # labels in choice order, for the closed dropdown ("South-East, South")
        "selected_orientation_labels": [
            label for value, label in Crag.Orientation.choices if value in orientations
        ],
        # (field, label, chosen minimum as a string or "") per age group
        "age_ratings": [
            (field, label, str(min_ratings.get(field, "")))
            for label, field in AGE_FIELDS.values()
        ],
        "star_choices": [("5", "5 stars"), ("4", "4+ stars"), ("3", "3+ stars"), ("2", "2+ stars"), ("1", "1+ stars")],
        "selected_max_approach": max_approach,
        "stroller_approach": stroller_approach,
        "stroller_base": stroller_base,
        "selected_avoid": avoid,
        "orientation_choices": Crag.Orientation.choices,
        "approach_choices": APPROACH_CHOICES,
        "sort_choices": [(value, label) for value, (label, _) in SORT_CHOICES.items()],
        "selected_sort": sort,
        # "Clear filters" keeps the search text and the sort order (not a filter)
        "clear_filters_url": with_query(
            reverse("crags:list"),
            {"q": query, "sort": "" if sort == DEFAULT_SORT else sort},
        ),
        "hazards": hazards,
        "active_filters": active_filters,
        "filters_open": bool(active_filters) or "f" in get,
    }
    return render(request, "crags/crag_list.html", context)


@cache_control(private=True, max_age=SUGGESTIONS_MAX_AGE)
def crag_suggestions(request):
    """Names for the search box's type-ahead (static/js/crag-search.js).

    All public crags and their areas, fetched once when the search box is first
    used, so the list page itself stays small. Only public data, so the browser
    may keep it for a few minutes ("private": not shared caches, since the
    response can carry cookies).
    """
    crags = Crag.objects.public().order_by("name").values_list("pk", "name", "area__name")
    areas = (
        Area.objects.filter(crags__status__in=Crag.PUBLIC_STATUSES)
        .distinct()
        .order_by("name")
        .values_list("name", flat=True)
    )
    return JsonResponse(
        {
            "areas": list(areas),
            "crags": [
                {"name": name, "area": area, "url": reverse("crags:detail", args=[pk])}
                for pk, name, area in crags
            ],
        }
    )


@offline_cacheable
def crag_detail(request, pk):
    crag = get_object_or_404(
        visible_crags(request.user).select_related("created_by").prefetch_related(
            "photos", "approach_features", "base_features", "guidebooks"
        ),
        pk=pk,
    )
    approach_features = list(crag.approach_features.all())
    base_features = list(crag.base_features.all())
    can_edit = request.user.is_authenticated and (
        request.user.is_staff or crag.created_by_id == request.user.id
    )
    community = crag.ratings.aggregate(
        babies=Avg("rating_babies"),
        babies_n=Count("rating_babies"),
        ages_2_4=Avg("rating_ages_2_4"),
        ages_2_4_n=Count("rating_ages_2_4"),
        ages_5_plus=Avg("rating_ages_5_plus"),
        ages_5_plus_n=Count("rating_ages_5_plus"),
    )
    can_rate = (
        request.user.is_authenticated
        and crag.status == Crag.Status.PUBLISHED
        and crag.created_by_id != request.user.id
    )
    my_rating = (
        crag.ratings.filter(user=request.user).first() if can_rate else None
    )
    return render(
        request,
        "crags/crag_detail.html",
        {
            "crag": crag,
            "can_edit": can_edit,
            "can_publish": can_publish_now(request.user, crag),
            "can_return": can_return_now(request.user, crag),
            "can_reject": can_reject_now(request.user, crag),
            "min_reason_length": Crag.MIN_REASON_LENGTH,
            "next": return_target(request),
            "community": community,
            "can_rate": can_rate,
            "my_rating": my_rating,
            "comments": crag.comments.select_related("user"),
            "review": review_context(request.user, crag),
            "can_suggest": can_suggest(request.user, crag),
            "change_requests": requests_for_crag_page(request.user, crag),
            "handles_changes": can_handle(request.user, crag),
            "can_comment": request.user.is_authenticated
            and crag.status == Crag.Status.PUBLISHED,
            "comment_max_length": CragComment.MAX_LENGTH,
            "scores": range(1, 6),
            "approach_features": approach_features,
            "approach_stroller_friendly": any(
                feature.slug == "stroller_friendly"
                for feature in approach_features
            ),
            "base_features": base_features,
            "base_stroller_friendly": any(
                feature.slug == "stroller_friendly"
                for feature in base_features
            ),
        },
    )


@login_required
@require_POST
def crag_rate(request, pk):
    crag = get_object_or_404(Crag.objects.published(), pk=pk)
    if crag.created_by_id == request.user.id:
        messages.error(request, "You cannot rate your own crag.")
        return redirect("crags:detail", pk=pk)

    values = {}
    for field in ("rating_babies", "rating_ages_2_4", "rating_ages_5_plus"):
        raw = request.POST.get(field, "")
        if raw == "":
            values[field] = None
        elif raw in ("1", "2", "3", "4", "5"):
            values[field] = int(raw)
        else:
            messages.error(request, "Invalid rating.")
            return redirect("crags:detail", pk=pk)

    if all(v is None for v in values.values()):
        CragRating.objects.filter(crag=crag, user=request.user).delete()
        messages.success(request, "Your rating was removed.")
    else:
        _, created = CragRating.objects.update_or_create(
            crag=crag, user=request.user, defaults=values
        )
        # email only for a new rating, not every change of it
        notify_owner(
            crag.created_by, Notification.Kind.RATING, crag, request.user, email=created
        )
        messages.success(request, "Thanks for rating!")
    return redirect("crags:detail", pk=pk)


@login_required
@require_POST
def comment_add(request, pk):
    crag = get_object_or_404(Crag.objects.published(), pk=pk)
    text = request.POST.get("text", "").strip()
    if not text:
        messages.error(request, "Please write a comment.")
    elif len(text) > CragComment.MAX_LENGTH:
        messages.error(
            request, f"Comments can be at most {CragComment.MAX_LENGTH} characters."
        )
    else:
        CragComment.objects.create(crag=crag, user=request.user, text=text)
        notify_owner(crag.created_by, Notification.Kind.COMMENT, crag, request.user)
        messages.success(request, "Comment added.")
    return redirect(reverse("crags:detail", args=[crag.pk]) + "#comments")


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(CragComment, pk=pk)
    if not (request.user.is_staff or comment.user_id == request.user.id):
        raise PermissionDenied
    comment.delete()
    messages.success(request, "Comment deleted.")
    return redirect(reverse("crags:detail", args=[comment.crag_id]) + "#comments")


@login_required
def notification_list(request):
    """Latest notifications; opening the page marks them all as read."""
    mine = Notification.objects.filter(user=request.user)
    mine.filter(
        read_at__lt=timezone.now() - timedelta(days=Notification.KEEP_READ_DAYS)
    ).delete()
    notifications = list(
        mine.exclude(crag__status=Crag.Status.REMOVED).select_related("crag", "actor")[:50]
    )
    # after fetching, so this page can still highlight what was new
    Notification.unread_for(request.user).update(read_at=timezone.now())
    return render(request, "crags/notifications.html", {"notifications": notifications})


@login_required
@require_POST
def review_reply(request, pk):
    """A message in the private review thread (submitter or moderator)."""
    crag = get_object_or_404(Crag.objects.exclude(status=Crag.Status.REMOVED), pk=pk)
    if not can_see_review(request.user, crag):
        raise PermissionDenied
    back = detail_url(crag, request) + "#review"
    if crag.status not in ReviewMessage.OPEN_STATUSES:
        messages.error(request, "This review is closed.")
        return redirect(back)
    text = request.POST.get("text", "").strip()
    if not text:
        messages.error(request, "Please write a message.")
    elif len(text) > ReviewMessage.MAX_LENGTH:
        messages.error(
            request, f"Messages can be at most {ReviewMessage.MAX_LENGTH} characters."
        )
    else:
        message = ReviewMessage.objects.create(crag=crag, author=request.user, text=text)
        notify_review_message(message)
        logger.info("review message crag=%s user=%s", crag.pk, request.user.pk)
        messages.success(request, "Message sent.")
    return redirect(back)


@login_required
def notification_settings(request):
    """Per notification type: in the app and/or by email (crags/notifications.py)."""
    user = request.user
    types = types_for(user)
    if request.method == "POST":
        saved = dict(user.notification_settings or {})
        for kind in types:
            saved[kind.key] = {
                channel: f"{kind.key}-{channel}" in request.POST for channel in CHANNELS
            }
        user.notification_settings = saved
        user.save(update_fields=["notification_settings"])
        logger.info("notification settings saved user=%s", user.pk)
        messages.success(request, "Notification settings saved.")
        return redirect("notification_settings")
    rows = [
        {
            "key": kind.key,
            "label": kind.label,
            "in_app": wants(user, kind.key, "in_app"),
            "email": wants(user, kind.key, "email"),
        }
        for kind in types
    ]
    return render(request, "crags/notification_settings.html", {"rows": rows})


@login_required
def crag_mine(request):
    crags = (
        Crag.objects.filter(created_by=request.user)
        .select_related("area")
        .order_by("-updated_at")
    )
    return render(request, "crags/crag_mine.html", {"crags": crags})


@login_required
def crag_create(request):
    can_publish = request.user.has_perm(PUBLISH_PERM)
    if request.method == "POST":
        publish = request.POST.get("action") == "publish"
        if publish and not can_publish:
            raise PermissionDenied
        form = CragForm(request.POST, request.FILES)
        photo_form = BulkPhotoForm(request.POST)
        uploads = request.FILES.getlist("images")

        if form.is_valid():
            converted = []
            photo_coordinates = None
            uploads_valid = True
            if len(uploads) > MAX_FILES_PER_UPLOAD:
                uploads_valid = False
                form.add_error(
                    None, f"Select no more than {MAX_FILES_PER_UPLOAD} images at a time."
                )
            elif uploads:
                if photo_form.is_valid():
                    # read GPS from the originals, before process_image() drops it
                    if not form.has_coordinates:
                        photo_coordinates = coordinates_from_photos(
                            uploads, photo_form.cleaned_data["category"]
                        )
                    for upload in uploads:
                        try:
                            converted.append(process_image(upload))
                        except ValidationError as exc:
                            uploads_valid = False
                            form.add_error(None, f"{upload.name}: {exc.messages[0]}")
                else:
                    uploads_valid = False

            if uploads_valid and not form.errors:
                crag = form.save(commit=False)
                if photo_coordinates:
                    crag.latitude, crag.longitude = photo_coordinates
                crag.created_by = request.user
                crag.status = Crag.Status.DRAFT
                crag.save()
                form.save_m2m()
                if publish:
                    crag.transition(Crag.Status.PUBLISHED, request.user)
                    messages.success(request, "Crag published.")
                elif request.POST.get("action") == "submit":
                    crag.transition(Crag.Status.PENDING, request.user)
                    messages.success(request, "Submitted. We will review this crag.")
                else:
                    messages.success(request, "Draft saved.")
                for content in converted:
                    Photo.objects.create(
                        crag=crag,
                        image=content,
                        category=photo_form.cleaned_data["category"],
                        uploaded_by=request.user,
                    )
                logger.info(
                    "crag created id=%s user=%s status=%s",
                    crag.pk, request.user.pk, crag.status,
                )
                if converted:
                    logger.info(
                        "photos uploaded crag=%s user=%s count=%s",
                        crag.pk, request.user.pk, len(converted),
                    )
                    messages.success(request, f"Uploaded {len(converted)} photo(s).")
                if photo_coordinates:
                    report_photo_coordinates(request, crag)
                return redirect("crags:detail", pk=crag.pk)
    else:
        form = CragForm()
        photo_form = BulkPhotoForm()

    return render(
        request,
        "crags/crag_form.html",
        {
            "form": form,
            "photo_form": photo_form,
            "allow_photo_upload": True,
            "max_files": MAX_FILES_PER_UPLOAD,
            "title": "Add a new crag",
            "note": "",
            "can_publish": can_publish,
        },
    )


@login_required
def crag_edit(request, pk):
    crag = get_object_or_404(editable_crags(request.user), pk=pk)
    existing = crag.photos.count()
    had_coordinates = crag.latitude is not None or crag.longitude is not None

    if request.method == "POST":
        publish = request.POST.get("action") == "publish"
        returning = request.POST.get("action") == "return"
        if (publish or returning) and not request.user.has_perm(PUBLISH_PERM):
            raise PermissionDenied
        form = CragForm(request.POST, request.FILES, instance=crag)
        photo_form = BulkPhotoForm(request.POST)
        uploads = request.FILES.getlist("images")

        if form.is_valid():
            converted = []
            photo_coordinates = None
            uploads_valid = True
            if returning and reason_error(request.POST.get("reason")):
                uploads_valid = False
                form.add_error(None, reason_error(request.POST.get("reason")))
            elif len(uploads) > MAX_FILES_PER_UPLOAD:
                uploads_valid = False
                form.add_error(
                    None, f"Select no more than {MAX_FILES_PER_UPLOAD} images at a time."
                )
            elif not request.user.is_staff and existing + len(uploads) > MAX_PHOTOS_PER_CRAG:
                uploads_valid = False
                form.add_error(
                    None,
                    f"A crag can have no more than {MAX_PHOTOS_PER_CRAG} photos. "
                    f"You can add {max(MAX_PHOTOS_PER_CRAG - existing, 0)} more.",
                )
            elif uploads:
                if photo_form.is_valid():
                    # read GPS from the originals, before process_image() drops it
                    if not had_coordinates and not form.has_coordinates:
                        photo_coordinates = coordinates_from_photos(
                            uploads, photo_form.cleaned_data["category"]
                        )
                    for upload in uploads:
                        try:
                            converted.append(process_image(upload))
                        except ValidationError as exc:
                            uploads_valid = False
                            form.add_error(None, f"{upload.name}: {exc.messages[0]}")
                else:
                    uploads_valid = False

            if uploads_valid and not form.errors:
                crag = form.save(commit=False)
                if photo_coordinates:
                    crag.latitude, crag.longitude = photo_coordinates
                crag.save()
                form.save_m2m()
                resubmit = (
                    request.POST.get("action") == "submit"
                    # any change to a published crag needs a new review,
                    # unless the editor may publish it themselves
                    or (
                        crag.status == Crag.Status.PUBLISHED
                        and not request.user.has_perm("crags.can_publish_crag")
                    )
                )
                if resubmit and Crag.Status.PENDING in crag.ALLOWED_TRANSITIONS[crag.status]:
                    # optional note for the reviewers, shown in the review thread
                    note = request.POST.get("review_note", "").strip()[:ReviewMessage.MAX_LENGTH]
                    crag.transition(Crag.Status.PENDING, request.user, note)
                if publish and crag.status != Crag.Status.PUBLISHED:
                    try:
                        crag.transition(Crag.Status.PUBLISHED, request.user)
                    except (InvalidTransition, ValidationError) as exc:
                        messages.error(request, f"Saved, but not published: {exc.messages[0]}")
                    else:
                        messages.success(request, "Crag published.")
                if returning:
                    try:
                        crag.transition(
                            Crag.Status.NEEDS_CHANGES, request.user, request.POST.get("reason")
                        )
                    except (InvalidTransition, ValidationError) as exc:
                        messages.error(request, f"Saved, but not returned: {exc.messages[0]}")
                    else:
                        messages.success(request, "Sent back to the submitter.")
                for content in converted:
                    Photo.objects.create(
                        crag=crag,
                        image=content,
                        category=photo_form.cleaned_data["category"],
                        uploaded_by=request.user,
                    )
                messages.success(request, "Changes saved.")
                logger.info(
                    "crag updated id=%s user=%s status=%s",
                    crag.pk, request.user.pk, crag.status,
                )
                if converted:
                    notify_owner(
                        crag.created_by, Notification.Kind.PHOTO, crag, request.user,
                        len(converted),
                    )
                    logger.info(
                        "photos uploaded crag=%s user=%s count=%s",
                        crag.pk, request.user.pk, len(converted),
                    )
                    messages.success(request, f"Uploaded {len(converted)} photo(s).")
                if photo_coordinates:
                    report_photo_coordinates(request, crag)
                return redirect(return_target(request) or detail_url(crag, request))
    else:
        form = CragForm(instance=crag)
        photo_form = BulkPhotoForm()

    note = ""
    if crag.status == Crag.Status.PUBLISHED and not request.user.has_perm(
        "crags.can_publish_crag"
    ):
        note = "Changes to published crags will be reviewed again."

    return render(
        request,
        "crags/crag_form.html",
        {
            "form": form,
            "photo_form": photo_form,
            "allow_photo_upload": True,
            "max_files": MAX_FILES_PER_UPLOAD,
            "crag": crag,
            "title": f"{crag.name} bearbeiten",
            "note": note,
            # on the edit page a publisher may also save an already published crag as is
            "can_publish": can_publish_now(request.user, crag)
            or (
                request.user.has_perm(PUBLISH_PERM)
                and crag.status == Crag.Status.PUBLISHED
            ),
            "can_return": can_return_now(request.user, crag),
            "min_reason_length": Crag.MIN_REASON_LENGTH,
            # publishers editing a published crag only need "Save and publish":
            # "Submit for review" would take the crag offline again
            "hide_draft_and_submit": request.user.has_perm(PUBLISH_PERM)
            and crag.status == Crag.Status.PUBLISHED,
            "can_remove": removable_crags(request.user).filter(pk=crag.pk).exists(),
            "next": return_target(request),
        },
    )


@login_required
def photo_add(request, pk):
    crag = get_object_or_404(editable_crags(request.user), pk=pk)

    if not request.user.is_staff and crag.photos.count() >= MAX_PHOTOS_PER_CRAG:
        messages.error(request, f"A crag can have no more than {MAX_PHOTOS_PER_CRAG} photos.")
        return redirect("crags:detail", pk=crag.pk)

    if request.method == "POST":
        form = BulkPhotoForm(request.POST)
        uploads = request.FILES.getlist("images")
        existing = crag.photos.count()

        if not uploads:
            messages.error(request, "Please select at least one image.")
        elif len(uploads) > MAX_FILES_PER_UPLOAD:
            messages.error(
                request,
                f"Select no more than {MAX_FILES_PER_UPLOAD} images at a time.",
            )
        elif not request.user.is_staff and existing + len(uploads) > MAX_PHOTOS_PER_CRAG:
            messages.error(
                request,
                f"A crag can have no more than {MAX_PHOTOS_PER_CRAG} photos. "
                f"You can add {MAX_PHOTOS_PER_CRAG - existing} more.",
            )
        elif form.is_valid():
            converted, errors = [], []
            photo_coordinates = None
            # read GPS from the originals, before process_image() drops it
            if crag.latitude is None and crag.longitude is None:
                photo_coordinates = coordinates_from_photos(
                    uploads, form.cleaned_data["category"]
                )
            for upload in uploads:
                try:
                    converted.append((upload, process_image(upload)))
                except ValidationError as exc:
                    errors.append(f"{upload.name}: {exc.messages[0]}")

            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                for _, content in converted:
                    Photo.objects.create(
                        crag=crag,
                        image=content,
                        category=form.cleaned_data["category"],
                        uploaded_by=request.user,
                    )
                logger.info(
                    "photos uploaded crag=%s user=%s count=%s",
                    crag.pk, request.user.pk, len(converted),
                )
                notify_owner(
                    crag.created_by, Notification.Kind.PHOTO, crag, request.user, len(converted)
                )
                messages.success(request, f"Uploaded {len(converted)} photo(s).")
                if photo_coordinates:
                    crag.latitude, crag.longitude = photo_coordinates
                    crag.save(update_fields=["latitude", "longitude", "updated_at"])
                    report_photo_coordinates(request, crag)
                return redirect("crags:detail", pk=crag.pk)
    else:
        form = BulkPhotoForm()

    return render(
        request,
        "crags/crag_photo_form.html",
        {"form": form, "crag": crag, "max_files": MAX_FILES_PER_UPLOAD},
    )


@login_required
@require_POST
def crag_publish(request, pk):
    if not request.user.has_perm(PUBLISH_PERM):
        raise PermissionDenied
    crag = get_object_or_404(Crag, pk=pk)
    try:
        crag.transition(Crag.Status.PUBLISHED, request.user)
    except (InvalidTransition, ValidationError) as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
    else:
        logger.info("crag published id=%s user=%s", crag.pk, request.user.pk)
        messages.success(request, f"Crag \u201c{crag.name}\u201d published.")
        return redirect(return_target(request) or detail_url(crag, request))
    return redirect(detail_url(crag, request))


@login_required
@require_POST
def crag_reject(request, pk):
    """Reject a pending crag (final; only a superuser can change the status again)."""
    if not request.user.has_perm(PUBLISH_PERM):
        raise PermissionDenied
    crag = get_object_or_404(Crag, pk=pk)
    try:
        crag.transition(Crag.Status.REJECTED, request.user)
    except (InvalidTransition, ValidationError) as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
    else:
        logger.info("crag rejected id=%s user=%s", crag.pk, request.user.pk)
        messages.success(request, f"Crag \u201c{crag.name}\u201d rejected.")
        return redirect(return_target(request) or detail_url(crag, request))
    return redirect(detail_url(crag, request))


@login_required
@require_POST
def crag_return(request, pk):
    """Send a crag back to its submitter ("Needs changes") with a reason."""
    if not request.user.has_perm(PUBLISH_PERM):
        raise PermissionDenied
    crag = get_object_or_404(Crag, pk=pk)
    reason = request.POST.get("reason", "")
    error = reason_error(reason)
    if error:
        messages.error(request, error)
        return redirect(detail_url(crag, request))
    try:
        crag.transition(Crag.Status.NEEDS_CHANGES, request.user, reason)
    except (InvalidTransition, ValidationError) as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
    else:
        logger.info("crag returned id=%s user=%s", crag.pk, request.user.pk)
        messages.success(request, f"Crag \u201c{crag.name}\u201d sent back to the submitter.")
        return redirect(return_target(request) or detail_url(crag, request))
    return redirect(detail_url(crag, request))


@login_required
@require_POST
def crag_delete(request, pk):
    """Soft delete: status REMOVED; a superuser can restore it in the admin."""
    crag = get_object_or_404(removable_crags(request.user), pk=pk)
    crag.transition(Crag.Status.REMOVED, request.user)
    logger.info("crag removed id=%s user=%s", crag.pk, request.user.pk)
    messages.success(request, f"Crag \u201c{crag.name}\u201d removed.")
    return redirect(return_target(request) or "crags:mine")


@login_required
@require_POST
def photo_delete(request, pk):
    photos = Photo.objects.filter(crag__in=editable_crags(request.user))
    photo = get_object_or_404(photos, pk=pk)
    crag_pk = photo.crag_id
    photo_pk = photo.pk
    photo.delete_files()  # also remove image and thumbnail from disk
    photo.delete()
    logger.info(
        "photo deleted id=%s crag=%s user=%s", photo_pk, crag_pk, request.user.pk
    )
    messages.success(request, "Photo deleted.")
    # from the edit page, next is the edit page itself (with its own return target)
    return redirect(return_target(request) or reverse("crags:detail", args=[crag_pk]))