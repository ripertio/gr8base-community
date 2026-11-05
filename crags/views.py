import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import BulkPhotoForm, CragForm, process_image
from .models import Area, Crag, Feature, Photo

logger = logging.getLogger(__name__)

MAX_PHOTOS_PER_CRAG = 8
MAX_FILES_PER_UPLOAD = 8

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

    crags = crags.distinct().order_by("name")
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
            "photos", "approach_features", "base_features"
        ),
        pk=pk,
    )
    approach_features = list(crag.approach_features.all())
    base_features = list(crag.base_features.all())
    can_edit = request.user.is_authenticated and (
        request.user.is_staff or crag.created_by_id == request.user.id
    )
    return render(
        request,
        "crags/crag_detail.html",
        {
            "crag": crag,
            "can_edit": can_edit,
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
        form = CragForm(request.POST)
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
                if request.POST.get("action") == "submit":
                    crag.status = Crag.Status.PENDING
                    messages.success(request, "Submitted. We will review this crag.")
                else:
                    crag.status = Crag.Status.DRAFT
                    messages.success(request, "Draft saved.")
                crag.save()
                form.save_m2m()
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
        form = CragForm(request.POST, instance=crag)
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
                if request.POST.get("action") == "submit":
                    crag.status = Crag.Status.PENDING
                elif crag.status == Crag.Status.PUBLISHED and not request.user.is_staff:
                    # any change to a published crag needs a new review
                    crag.status = Crag.Status.PENDING
                crag.save()
                form.save_m2m()
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
    if crag.status == Crag.Status.PUBLISHED and not request.user.is_staff:
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
def crag_delete(request, pk):
    crag = get_object_or_404(editable_crags(request.user), pk=pk)
    for photo in crag.photos.all():
        photo.image.delete(save=False)  # also remove the file from disk
    name = crag.name
    crag_pk = crag.pk
    crag.delete()
    logger.info("crag deleted id=%s user=%s", crag_pk, request.user.pk)
    messages.success(request, f"Crag \u201c{name}\u201d deleted.")
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