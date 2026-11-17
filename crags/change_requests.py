""""Suggest a change": other users point out what is wrong or outdated on a crag.

A change request is private: its requester, the crag's creator and moderators
see it. The creator (or a moderator) edits the crag as usual and closes the
request as done or declined. Suggested photos stay private until they are
accepted into the gallery; closing the request deletes the rest.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import process_image
from .models import ChangeRequest, ChangeRequestMessage, ChangeRequestPhoto, Crag, Notification, Photo
from .notifications import (
    can_moderate, notify_change_request, notify_change_request_closed,
    notify_change_request_message, notify_owner,
)

logger = logging.getLogger(__name__)

MAX_FILES_PER_SUGGESTION = 8


def can_suggest(user, crag):
    """Logged in, a published crag, and not your own (you can edit that directly)."""
    return (
        user.is_authenticated
        and crag.status == Crag.Status.PUBLISHED
        and crag.created_by_id != user.pk
    )


def can_handle(user, crag):
    """The crag's creator and moderators edit the crag and close its requests."""
    return user.is_authenticated and (crag.created_by_id == user.pk or can_moderate(user))


def can_view(user, change_request):
    return user.is_authenticated and (
        change_request.requester_id == user.pk or can_handle(user, change_request.crag)
    )


def max_photos_per_crag():
    from .views import MAX_PHOTOS_PER_CRAG

    return MAX_PHOTOS_PER_CRAG


def detail_url(change_request):
    return reverse("crags:change_request", args=[change_request.pk])


@login_required
def suggest(request, pk):
    crag = get_object_or_404(Crag.objects.published(), pk=pk)
    if crag.created_by_id == request.user.pk:
        messages.info(request, "This is your crag: you can edit it directly.")
        return redirect("crags:edit", pk=crag.pk)

    errors = []
    values = {"topic": ChangeRequest.Topic.OTHER, "text": "", "category": Photo.Category.CRAG}
    if request.method == "POST":
        values = {
            "topic": request.POST.get("topic", ""),
            "text": request.POST.get("text", "").strip(),
            "category": request.POST.get("category", ""),
        }
        uploads = request.FILES.getlist("images")
        if values["topic"] not in ChangeRequest.Topic.values:
            values["topic"] = ChangeRequest.Topic.OTHER
        if values["category"] not in Photo.Category.values:
            values["category"] = Photo.Category.CRAG
        if not values["text"] and not uploads:
            errors.append("Describe the change or add photos.")
        if len(values["text"]) > ChangeRequest.MAX_LENGTH:
            errors.append(f"At most {ChangeRequest.MAX_LENGTH} characters, please.")
        if len(uploads) > MAX_FILES_PER_SUGGESTION:
            errors.append(f"Select no more than {MAX_FILES_PER_SUGGESTION} images at a time.")
        converted = []
        if not errors:
            for upload in uploads:
                try:
                    converted.append(process_image(upload))
                except ValidationError as exc:
                    errors.append(f"{upload.name}: {exc.messages[0]}")
        if not errors:
            change_request = ChangeRequest.objects.create(
                crag=crag, requester=request.user, topic=values["topic"], text=values["text"]
            )
            for content in converted:
                suggestion = ChangeRequestPhoto(
                    change_request=change_request, category=values["category"],
                    uploaded_by=request.user,
                )
                suggestion.image.save("photo.webp", content, save=True)
            notify_change_request(change_request)
            logger.info(
                "change request created id=%s crag=%s user=%s photos=%s",
                change_request.pk, crag.pk, request.user.pk, len(converted),
            )
            messages.success(
                request,
                "Thank you! Your suggestion was sent to the crag's creator and the moderators.",
            )
            return redirect(detail_url(change_request))

    return render(
        request,
        "crags/change_request_form.html",
        {
            "crag": crag,
            "errors": errors,
            "values": values,
            "topics": ChangeRequest.Topic.choices,
            "categories": Photo.Category.choices,
            "max_files": MAX_FILES_PER_SUGGESTION,
            "max_length": ChangeRequest.MAX_LENGTH,
        },
    )


def get_visible(request, pk):
    change_request = get_object_or_404(
        ChangeRequest.objects.select_related("crag", "crag__created_by", "requester", "closed_by"),
        pk=pk,
    )
    # Not found rather than forbidden: others must not learn that it exists.
    if not can_view(request.user, change_request) or change_request.crag.status == Crag.Status.REMOVED:
        raise Http404
    return change_request


@login_required
def change_request_detail(request, pk):
    change_request = get_visible(request, pk)
    crag = change_request.crag
    handle = can_handle(request.user, crag) and change_request.is_open
    photo_count = crag.photos.count()
    return render(
        request,
        "crags/change_request_detail.html",
        {
            "change_request": change_request,
            "crag": crag,
            "entries": change_request.messages.select_related("author"),
            "photos": list(change_request.photos.all()),
            "can_reply": change_request.is_open,
            "can_handle": handle,
            "categories": Photo.Category.choices,
            "photo_count": photo_count,
            "max_photos": max_photos_per_crag(),
            "photo_limit": not request.user.is_staff,
            "max_length": ChangeRequest.MAX_LENGTH,
        },
    )


@login_required
@require_POST
def reply(request, pk):
    change_request = get_visible(request, pk)
    back = detail_url(change_request) + "#messages"
    if not change_request.is_open:
        messages.error(request, "This change request is closed.")
        return redirect(back)
    text = request.POST.get("text", "").strip()
    if not text:
        messages.error(request, "Please write a message.")
    elif len(text) > ChangeRequest.MAX_LENGTH:
        messages.error(request, f"Messages can be at most {ChangeRequest.MAX_LENGTH} characters.")
    else:
        message = ChangeRequestMessage.objects.create(
            change_request=change_request, author=request.user, text=text
        )
        notify_change_request_message(message)
        logger.info("change request message id=%s user=%s", change_request.pk, request.user.pk)
        messages.success(request, "Message sent.")
    return redirect(back)


def accept_photo(suggestion, category):
    """Copy a suggested photo into the crag's gallery (with a thumbnail)."""
    photo = Photo(
        crag=suggestion.change_request.crag, category=category,
        uploaded_by=suggestion.uploaded_by,
    )
    with suggestion.image.open("rb") as source:
        photo.image.save("photo.webp", ContentFile(source.read()), save=False)
    photo.save()
    return photo


@login_required
@require_POST
def close(request, pk):
    change_request = get_visible(request, pk)
    crag = change_request.crag
    if not can_handle(request.user, crag):
        raise PermissionDenied
    back = detail_url(change_request)
    if not change_request.is_open:
        messages.error(request, "This change request is already closed.")
        return redirect(back)

    done = request.POST.get("action") == "done"
    note = request.POST.get("text", "").strip()
    if len(note) > ChangeRequest.MAX_LENGTH:
        messages.error(request, f"Messages can be at most {ChangeRequest.MAX_LENGTH} characters.")
        return redirect(back)

    suggestions = list(change_request.photos.all())
    ticked = set(request.POST.getlist("accept"))
    accepted = [s for s in suggestions if str(s.pk) in ticked] if done else []
    if accepted and not request.user.is_staff:
        room = max_photos_per_crag() - crag.photos.count()
        if len(accepted) > room:
            messages.error(
                request,
                f"A crag can have no more than {max_photos_per_crag()} photos. "
                f"You can accept {max(room, 0)} more, or delete an older photo first.",
            )
            return redirect(back)

    with transaction.atomic():
        for suggestion in accepted:
            category = request.POST.get(f"category-{suggestion.pk}", suggestion.category)
            if category not in Photo.Category.values:
                category = suggestion.category
            accept_photo(suggestion, category)
        change_request.status = (
            ChangeRequest.Status.DONE if done else ChangeRequest.Status.DECLINED
        )
        change_request.closed_at = timezone.now()
        change_request.closed_by = request.user
        change_request.save()
        ChangeRequestMessage.objects.create(
            change_request=change_request, author=request.user, text=note,
            kind=ChangeRequestMessage.Kind.DONE if done else ChangeRequestMessage.Kind.DECLINED,
        )
        # accepted ones were copied; the rest is not kept (files go with the rows)
        change_request.photos.all().delete()

    notify_change_request_closed(change_request, note)
    if accepted:
        # e.g. a moderator handled it: the creator learns about the new photos
        notify_owner(
            crag.created_by, Notification.Kind.PHOTO, crag, request.user, len(accepted)
        )
    logger.info(
        "change request closed id=%s user=%s status=%s accepted=%s",
        change_request.pk, request.user.pk, change_request.status, len(accepted),
    )
    if done:
        added = f" {len(accepted)} photo(s) added to the gallery." if accepted else ""
        messages.success(request, f"Marked as done.{added}")
    else:
        messages.success(request, "Change request declined.")
    return redirect(back)


def requests_for_crag_page(user, crag):
    """Change requests to list on the crag page: all open ones for its handlers,
    otherwise the user's own."""
    if not user.is_authenticated:
        return []
    requests = crag.change_requests.select_related("requester")
    if can_handle(user, crag):
        return list(requests.filter(status=ChangeRequest.Status.OPEN))
    return list(requests.filter(requester=user))
