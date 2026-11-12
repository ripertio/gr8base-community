import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import BulkPhotoForm, CragForm, process_image
from .models import Area, Crag, CragComment, CragRating, Feature, InvalidTransition, Photo

logger = logging.getLogger(__name__)

MAX_PHOTOS_PER_CRAG = 8
MAX_FILES_PER_UPLOAD = 8

PUBLISH_PERM = "crags.can_publish_crag"


def can_publish_now(user, crag):
    """Publish buttons: the user may publish and the crag is waiting for review."""
    return user.has_perm(PUBLISH_PERM) and crag.status == Crag.Status.PENDING


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


AGE_FIELDS = {
    "babies": ("Babies", "rating_babies"),
    "ages_2_4": ("Ages 2–4", "rating_ages_2_4"),
    "ages_5_plus": ("Ages 5+", "rating_ages_5_plus"),
}
APPROACH_CHOICES = (5, 10, 15, 20, 30)
STROLLER_SLUG = "stroller_friendly"


def crag_list(request):
    crags = Crag.objects.select_related("area").public()
    get = request.GET
    query = get.get("q", "").strip()
    area_name = get.get("area", "")
    min_rating = get.get("rating", "")
    age = get.get("age", "")
    orientation = get.get("orientation", "")
    max_approach = get.get("max_approach", "")
    stroller_approach = get.get("stroller_approach") == "1"
    stroller_base = get.get("stroller_base") == "1"

    hazards = Feature.objects.exclude(slug=STROLLER_SLUG).order_by("label")
    hazard_slugs = {h.slug for h in hazards}
    avoid = [slug for slug in get.getlist("avoid") if slug in hazard_slugs]

    if area_name and not Area.objects.filter(name=area_name).exists():
        area_name = ""
    if not (min_rating.isdecimal() and 1 <= int(min_rating) <= 5):
        min_rating = ""
    if age not in AGE_FIELDS:
        age = ""
    if orientation not in Crag.Orientation.values:
        orientation = ""
    if not (max_approach.isdecimal() and int(max_approach) in APPROACH_CHOICES):
        max_approach = ""

    if query:
        crags = crags.filter(
            Q(name__icontains=query)
            | Q(area__name__icontains=query)
            | Q(description__icontains=query)
        )

    if area_name:
        crags = crags.filter(area__name=area_name)

    if age:
        field = AGE_FIELDS[age][1]
        if min_rating:
            crags = crags.filter(**{f"{field}__gte": min_rating})
        else:
            crags = crags.filter(**{f"{field}__isnull": False})
    elif min_rating:
        crags = crags.filter(
            Q(rating_babies__gte=min_rating)
            | Q(rating_ages_2_4__gte=min_rating)
            | Q(rating_ages_5_plus__gte=min_rating)
        )

    if orientation:
        crags = crags.filter(orientation=orientation)

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

    crags = list(crags.distinct().order_by("name"))
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
    for crag in crags:
        crag.community = averages.get(crag.pk, {})
        crag.comment_count = comment_counts.get(crag.pk, 0)
    areas = (
        Area.objects.filter(crags__status__in=Crag.PUBLIC_STATUSES)
        .distinct()
        .order_by("name")
    )

    active_filters = (
        bool(area_name)
        + bool(min_rating)
        + bool(age)
        + bool(orientation)
        + bool(max_approach)
        + stroller_approach
        + stroller_base
        + len(avoid)
    )

    context = {
        "crags": crags,
        "areas": areas,
        "query": query,
        "selected_area": area_name,
        "selected_rating": min_rating,
        "selected_age": age,
        "selected_orientation": orientation,
        "selected_max_approach": max_approach,
        "stroller_approach": stroller_approach,
        "stroller_base": stroller_base,
        "selected_avoid": avoid,
        "age_choices": [(key, label) for key, (label, _) in AGE_FIELDS.items()],
        "orientation_choices": Crag.Orientation.choices,
        "approach_choices": APPROACH_CHOICES,
        "hazards": hazards,
        "active_filters": active_filters,
        "filters_open": bool(active_filters) or "f" in get,
    }
    return render(request, "crags/crag_list.html", context)


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
            "community": community,
            "can_rate": can_rate,
            "my_rating": my_rating,
            "comments": crag.comments.select_related("user"),
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
        CragRating.objects.update_or_create(
            crag=crag, user=request.user, defaults=values
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
def crag_mine(request):
    crags = (
        Crag.objects.filter(created_by=request.user)
        .select_related("area")
        .order_by("-updated_at")
    )
    return render(request, "crags/crag_mine.html", {"crags": crags})


@login_required
def crag_create(request):
    if request.method == "POST":
        form = CragForm(request.POST, request.FILES)
        photo_form = BulkPhotoForm(request.POST)
        uploads = request.FILES.getlist("images")

        if form.is_valid():
            converted = []
            uploads_valid = True
            if len(uploads) > MAX_FILES_PER_UPLOAD:
                uploads_valid = False
                form.add_error(
                    None, f"Select no more than {MAX_FILES_PER_UPLOAD} images at a time."
                )
            elif uploads:
                if photo_form.is_valid():
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
                crag.created_by = request.user
                crag.status = Crag.Status.DRAFT
                crag.save()
                form.save_m2m()
                if request.POST.get("action") == "submit":
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
        },
    )


@login_required
def crag_edit(request, pk):
    crag = get_object_or_404(editable_crags(request.user), pk=pk)
    existing = crag.photos.count()

    if request.method == "POST":
        publish = request.POST.get("action") == "publish"
        if publish and not request.user.has_perm(PUBLISH_PERM):
            raise PermissionDenied
        form = CragForm(request.POST, request.FILES, instance=crag)
        photo_form = BulkPhotoForm(request.POST)
        uploads = request.FILES.getlist("images")

        if form.is_valid():
            converted = []
            uploads_valid = True
            if len(uploads) > MAX_FILES_PER_UPLOAD:
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
                    crag.transition(Crag.Status.PENDING, request.user)
                if publish:
                    try:
                        crag.transition(Crag.Status.PUBLISHED, request.user)
                    except (InvalidTransition, ValidationError) as exc:
                        messages.error(request, f"Saved, but not published: {exc.messages[0]}")
                    else:
                        messages.success(request, "Crag published.")
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
                    logger.info(
                        "photos uploaded crag=%s user=%s count=%s",
                        crag.pk, request.user.pk, len(converted),
                    )
                    messages.success(request, f"Uploaded {len(converted)} photo(s).")
                return redirect("crags:detail", pk=crag.pk)
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
            "can_publish": can_publish_now(request.user, crag),
            "can_remove": removable_crags(request.user).filter(pk=crag.pk).exists(),
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
                messages.success(request, f"Uploaded {len(converted)} photo(s).")
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
    return redirect("crags:detail", pk=crag.pk)


@login_required
@require_POST
def crag_delete(request, pk):
    """Soft delete: status REMOVED; a superuser can restore it in the admin."""
    crag = get_object_or_404(removable_crags(request.user), pk=pk)
    crag.transition(Crag.Status.REMOVED, request.user)
    logger.info("crag removed id=%s user=%s", crag.pk, request.user.pk)
    messages.success(request, f"Crag \u201c{crag.name}\u201d removed.")
    return redirect("crags:mine")


@login_required
@require_POST
def photo_delete(request, pk):
    photos = Photo.objects.filter(crag__in=editable_crags(request.user))
    photo = get_object_or_404(photos, pk=pk)
    crag_pk = photo.crag_id
    photo_pk = photo.pk
    photo.image.delete(save=False)  # also remove the file from disk
    photo.delete()
    logger.info(
        "photo deleted id=%s crag=%s user=%s", photo_pk, crag_pk, request.user.pk
    )
    messages.success(request, "Photo deleted.")
    if request.POST.get("next") == "edit":
        return redirect("crags:edit", pk=crag_pk)
    return redirect("crags:detail", pk=crag_pk)