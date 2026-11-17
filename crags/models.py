from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image
import io
import logging
import uuid

logger = logging.getLogger(__name__)

THUMBNAIL_EDGE = 640     # longest side; sharp enough for a full-width card on a phone
THUMBNAIL_QUALITY = 70   # ~90 KB instead of ~700 KB for a 1600px photo


def photo_upload_path(instance, filename):
    # Random name: the user's filename is never used
    return f"crags/{uuid.uuid4().hex}.webp"


def photo_thumbnail_upload_path(instance, filename):
    return f"crags/thumbs/{uuid.uuid4().hex}.webp"


def make_thumbnail_content(image_file):
    """Return a small WEBP ContentFile made from an already processed image."""
    image_file.open("rb")
    try:
        with Image.open(image_file) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE))
            buffer = io.BytesIO()
            img.save(buffer, format="WEBP", quality=THUMBNAIL_QUALITY, method=6)
    finally:
        image_file.close()
    return ContentFile(buffer.getvalue(), name="thumb.webp")

class Area(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Feature(models.Model):
    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=80)

    def __str__(self):
        return self.label


def guidebook_upload_path(instance, filename):
    # Random name: the user's filename is never used
    return f"guidebooks/{uuid.uuid4().hex}.webp"


class Guidebook(models.Model):
    name = models.CharField(max_length=250)
    url = models.URLField(blank=True)
    publish_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1800), MaxValueValidator(2100)],
    )
    publisher = models.CharField(max_length=200, blank=True)
    picture = models.ImageField(upload_to=guidebook_upload_path, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InvalidTransition(Exception):
    pass


class CragQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Crag.Status.PUBLISHED)

    def public(self):
        return self.filter(status__in=Crag.PUBLIC_STATUSES)


class ActiveCragManager(models.Manager.from_queryset(CragQuerySet)):
    """Default manager: hides removed (soft-deleted) crags everywhere on the site."""

    def get_queryset(self):
        return super().get_queryset().exclude(status=Crag.Status.REMOVED)


class Crag(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending review"
        PUBLISHED = "PUBLISHED", "Published"
        NEEDS_CHANGES = "NEEDS_CHANGES", "Needs changes"
        REJECTED = "REJECTED", "Rejected"
        REMOVED = "REMOVED", "Removed"
       # statuses that anonymous visitors may see
    PUBLIC_STATUSES = (Status.PUBLISHED, Status.PENDING)

    class Orientation(models.TextChoices):
        N = "N", "North"
        NE = "NE", "North-East"
        E = "E", "East"
        SE = "SE", "South-East"
        S = "S", "South"
        SW = "SW", "South-West"
        W = "W", "West"
        NW = "NW", "North-West"

    name = models.CharField(max_length=160)

    area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name="crags",
    )

    description = models.TextField(blank=True)

    approach_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    rating_babies = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
        null=True,
        blank=True,
    )

    rating_ages_2_4 = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
        null=True,
        blank=True,
    )

    rating_ages_5_plus = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
        null=True,
        blank=True,
    )

    approach_features = models.ManyToManyField(
        Feature,
        blank=True,
        related_name="+",
    )

    approach_assessed = models.BooleanField(default=False)

    base_features = models.ManyToManyField(
        Feature,
        blank=True,
        related_name="+",
    )

    base_assessed = models.BooleanField(default=False)

    guidebooks = models.ManyToManyField(
        Guidebook,
        blank=True,
        related_name="crags",
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    parking = models.TextField(blank=True)

    family_notes = models.TextField(blank=True)

    orientation = models.CharField(
        max_length=2,
        choices=Orientation.choices,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="crags",
    )

    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_crags",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # Shown to the submitter when a crag is returned.
    review_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveCragManager()
    all_objects = CragQuerySet.as_manager()  # includes removed crags (admin only)

    # status -> statuses it may move to via transition()
    ALLOWED_TRANSITIONS = {
        # DRAFT/NEEDS_CHANGES -> PUBLISHED: publishers skip the review step. Only code
        # that checks crags.can_publish_crag (views, admin actions) asks for PUBLISHED.
        Status.DRAFT: {Status.PENDING, Status.PUBLISHED, Status.REMOVED},
        Status.PENDING: {
            Status.PUBLISHED, Status.NEEDS_CHANGES, Status.REJECTED, Status.REMOVED,
        },
        Status.NEEDS_CHANGES: {Status.PENDING, Status.PUBLISHED, Status.REMOVED},
        Status.PUBLISHED: {Status.PENDING, Status.NEEDS_CHANGES, Status.REMOVED},
        Status.REJECTED: {Status.REMOVED},
        # a restored crag starts again as a private draft
        Status.REMOVED: {Status.DRAFT},
    }
    MIN_REASON_LENGTH = 10

    def transition(self, to, actor, reason="", force=False):
        """The only place that changes status; validates and sets audit fields.

        force=True skips the allowed-transitions table (superuser override in the admin).
        """
        to = self.Status(to)
        if to == self.status:
            raise InvalidTransition(f"Already {self.Status(self.status).label}.")
        if not force and to not in self.ALLOWED_TRANSITIONS[self.Status(self.status)]:
            raise InvalidTransition(f"Cannot change {self.status} to {to}.")
        reason = (reason or "").strip()
        if to == self.Status.NEEDS_CHANGES and len(reason) < self.MIN_REASON_LENGTH:
            raise ValidationError(
                f"A reason of at least {self.MIN_REASON_LENGTH} characters is required."
            )
        now = timezone.now()
        note = ""
        if to == self.Status.PENDING:
            note, reason = reason, ""  # optional note for the reviewers when (re)submitting
            self.submitted_at = now
            self.reviewed_by = None
            self.reviewed_at = None
            self.review_reason = ""
        elif to in (self.Status.REMOVED, self.Status.DRAFT):
            pass  # removing or restoring is not a review decision
        else:
            self.reviewed_by = actor
            self.reviewed_at = now
            self.review_reason = reason if to == self.Status.NEEDS_CHANGES else ""
        self.status = to
        self.save()
        entry = {
            self.Status.NEEDS_CHANGES: (ReviewMessage.Kind.RETURNED, reason),
            self.Status.PENDING: (ReviewMessage.Kind.SUBMITTED, note),
            self.Status.PUBLISHED: (ReviewMessage.Kind.PUBLISHED, ""),
            self.Status.REJECTED: (ReviewMessage.Kind.REJECTED, ""),
        }.get(to)
        if entry is not None:
            ReviewMessage.objects.create(crag=self, author=actor, kind=entry[0], text=entry[1])
        if to == self.Status.REMOVED:
            self.close_change_requests(actor)
        if to in (self.Status.PUBLISHED, self.Status.NEEDS_CHANGES):
            from .notifications import notify_in_app, notify_submitter

            notify_submitter(self)
            notify_in_app(
                self.created_by,
                Notification.Kind.PUBLISHED
                if to == self.Status.PUBLISHED
                else Notification.Kind.CHANGES_REQUESTED,
                self,
                actor,
            )
        elif to == self.Status.PENDING:
            from .notifications import notify_moderators

            notify_moderators(self, actor)

    def close_change_requests(self, actor):
        """On removal: decline open change requests and delete all suggested photos.

        Suggested photos are private and only kept while a request is open; a
        removed crag cannot take them any more (restoring it does not reopen them).
        """
        now = timezone.now()
        for change_request in self.change_requests.filter(status=ChangeRequest.Status.OPEN):
            change_request.status = ChangeRequest.Status.DECLINED
            change_request.closed_at = now
            change_request.closed_by = actor
            change_request.save()
            ChangeRequestMessage.objects.create(
                change_request=change_request, author=actor,
                kind=ChangeRequestMessage.Kind.DECLINED, text="The crag was removed.",
            )
        # files go with the rows (post_delete signal)
        ChangeRequestPhoto.objects.filter(change_request__crag=self).delete()

    def clean(self):
        super().clean()
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Latitude and longitude must be provided together.")

    class Meta:
        ordering = ["name"]
        permissions = [
            ("can_publish_crag", "Can publish and return crags"),
            ("can_remove_crag", "Can remove crags (soft delete)"),
        ]

    def __str__(self):
        return self.name

class Photo(models.Model):
    class Category(models.TextChoices):
        CRAG = "CRAG", "Crag"
        BASE_AREA = "BASE_AREA", "Base area"
        APPROACH = "APPROACH", "Approach"
        PARKING = "PARKING", "Parking"
        TERRAIN = "TERRAIN", "Surroundings"
        OTHER = "OTHER", "Other"

    crag = models.ForeignKey(
        Crag,
        on_delete=models.CASCADE,
        related_name="photos",
    )

    image = models.ImageField(upload_to=photo_upload_path)

    category = models.CharField(
        max_length=10,
        choices=Category.choices,
        default=Category.CRAG,
    )

    caption = models.CharField(max_length=250, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="photos",
    )

    # Small copy for cards and grids (generated on save), so pages don't load
    # the full-size image just to show a 220px preview.
    # db_default: code that doesn't know this column (the old version during a
    # deploy, or after a code-only rollback) can still insert photos.
    thumbnail = models.ImageField(
        upload_to=photo_thumbnail_upload_path, blank=True, editable=False,
        default="", db_default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._image_name_at_load = self.image.name

    def __str__(self):
        return f"Photo of {self.crag.name}"

    @property
    def thumbnail_url(self):
        """Thumbnail if there is one, otherwise the full image."""
        return (self.thumbnail or self.image).url

    def save(self, *args, **kwargs):
        image_changed = self.image.name != self._image_name_at_load
        super().save(*args, **kwargs)
        self._image_name_at_load = self.image.name
        if self.image and (image_changed or not self.thumbnail):
            self.make_thumbnail()

    def make_thumbnail(self):
        """(Re)create the thumbnail from the stored image. Returns True on success."""
        old = self.thumbnail.name
        try:
            content = make_thumbnail_content(self.image)
        except OSError as exc:
            logger.warning("thumbnail failed photo=%s (%s)", self.pk, type(exc).__name__)
            return False
        self.thumbnail.save("thumb.webp", content, save=False)
        Photo.objects.filter(pk=self.pk).update(thumbnail=self.thumbnail.name)
        if old and old != self.thumbnail.name:
            self.thumbnail.storage.delete(old)
        return True

    def delete_files(self):
        """Remove the image and thumbnail files from storage."""
        if self.thumbnail:
            self.thumbnail.delete(save=False)
        self.image.delete(save=False)


class CragRating(models.Model):
    """A community member's family rating of a crag (one row per user and crag)."""

    crag = models.ForeignKey(Crag, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crag_ratings"
    )
    rating_babies = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True
    )
    rating_ages_2_4 = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True
    )
    rating_ages_5_plus = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["crag", "user"], name="unique_rating_per_user"),
        ]

    def __str__(self):
        return f"{self.user} → {self.crag}"


class CragComment(models.Model):
    """A short comment by a registered user (deleted together with the user)."""

    MAX_LENGTH = 1000

    crag = models.ForeignKey(Crag, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crag_comments"
    )
    text = models.TextField(max_length=MAX_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user} on {self.crag}"


class Notification(models.Model):
    """In-app notice for a crag's creator (the counter next to their name).

    Only ids, the kind and a count are stored; the text is built when shown, so
    renaming a crag or deleting an account never leaves stale copies behind.
    Deleted with the recipient or the crag; the actor link is cleared when the
    actor's account is deleted.
    """

    class Kind(models.TextChoices):
        COMMENT = "COMMENT", "New comment"
        RATING = "RATING", "New rating"
        PHOTO = "PHOTO", "New photos"
        PUBLISHED = "PUBLISHED", "Published"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
        REVIEW_MESSAGE = "REVIEW_MESSAGE", "New message in a review"
        CHANGE_REQUEST = "CHANGE_REQUEST", "Change suggested"
        CHANGE_REQUEST_MESSAGE = "CHANGE_REQUEST_MESSAGE", "New message in a change request"
        CHANGE_REQUEST_CLOSED = "CHANGE_REQUEST_CLOSED", "Change request handled"

    # read notifications older than this are deleted when the list is opened
    KEEP_READ_DAYS = 180

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    crag = models.ForeignKey(Crag, on_delete=models.CASCADE, related_name="+")
    # for the change request kinds: where the notification leads
    change_request = models.ForeignKey(
        "ChangeRequest", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    count = models.PositiveSmallIntegerField(default=1)  # e.g. 3 photos in one go
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["user", "read_at"], name="notification_unread")]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.user}"

    @classmethod
    def unread_for(cls, user):
        """The user's unread notifications (the counter next to their name)."""
        return cls.objects.filter(user=user, read_at__isnull=True).exclude(
            crag__status=Crag.Status.REMOVED
        )

    @property
    def text(self):
        who = self.actor.username if self.actor else "Someone"
        name = f"“{self.crag.name}”"
        if self.kind == self.Kind.COMMENT:
            return f"{who} commented on {name}."
        if self.kind == self.Kind.RATING:
            return f"{who} rated {name}."
        if self.kind == self.Kind.PHOTO:
            photos = "a photo" if self.count == 1 else f"{self.count} photos"
            return f"{who} added {photos} to {name}."
        if self.kind == self.Kind.PUBLISHED:
            return f"{name} was published. Thank you for contributing!"
        if self.kind == self.Kind.REVIEW_MESSAGE:
            return f"{who} wrote in the review of {name}."
        if self.kind == self.Kind.CHANGE_REQUEST:
            return f"{who} suggested a change to {name}."
        if self.kind == self.Kind.CHANGE_REQUEST_MESSAGE:
            return f"{who} wrote in a change request for {name}."
        if self.kind == self.Kind.CHANGE_REQUEST_CLOSED:
            request = self.change_request
            if request is not None and request.status == ChangeRequest.Status.DONE:
                return f"Your change request for {name} was done. Thank you!"
            if request is not None and request.status == ChangeRequest.Status.DECLINED:
                return f"Your change request for {name} was declined."
            return f"Your change request for {name} was handled."
        return f"Changes were requested for {name}. Please edit it and submit it again."

    @property
    def url(self):
        if self.change_request_id:
            return reverse("crags:change_request", args=[self.change_request_id])
        url = reverse("crags:detail", args=[self.crag_id])
        if self.kind == self.Kind.COMMENT:
            return url + "#comments"
        if self.kind == self.Kind.REVIEW_MESSAGE:
            return url + "#review"
        return url


class ReviewMessage(models.Model):
    """The private review conversation of a crag: its submitter and the moderators.

    MESSAGE is something someone wrote; the other kinds are written by
    Crag.transition() so the thread also tells the story of the review
    (RETURNED carries the reason, SUBMITTED an optional note). Only the
    submitter and moderators see it. The author link is cleared when the
    author's account is deleted.
    """

    class Kind(models.TextChoices):
        MESSAGE = "MESSAGE", "Message"
        SUBMITTED = "SUBMITTED", "Submitted for review"
        RETURNED = "RETURNED", "Changes requested"
        PUBLISHED = "PUBLISHED", "Published"
        REJECTED = "REJECTED", "Rejected"

    MAX_LENGTH = 2000
    # replies are possible while the review is open
    OPEN_STATUSES = (Crag.Status.NEEDS_CHANGES, Crag.Status.PENDING)

    crag = models.ForeignKey(Crag, on_delete=models.CASCADE, related_name="review_messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MESSAGE)
    text = models.TextField(max_length=MAX_LENGTH, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.crag}"

    @property
    def author_name(self):
        return self.author.username if self.author else "Someone"


def suggested_photo_upload_path(instance, filename):
    # Random name; kept apart from the gallery until the photo is accepted
    return f"crags/suggested/{uuid.uuid4().hex}.webp"


class ChangeRequest(models.Model):
    """Someone (not the creator) suggests a change to a published crag.

    Private: the requester, the crag's creator and moderators see it. The
    creator or a moderator edits the crag as usual and closes the request as
    done or declined; suggested photos are accepted into the gallery or deleted.
    """

    class Topic(models.TextChoices):
        LOCATION = "LOCATION", "Location"
        APPROACH = "APPROACH", "Approach"
        PARKING = "PARKING", "Parking"
        BASE = "BASE", "Base"
        RATING = "RATING", "Family rating"
        PHOTOS = "PHOTOS", "Photos"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        DONE = "DONE", "Done"
        DECLINED = "DECLINED", "Declined"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    MAX_LENGTH = 2000

    crag = models.ForeignKey(Crag, on_delete=models.CASCADE, related_name="change_requests")
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    topic = models.CharField(max_length=10, choices=Topic.choices, default=Topic.OTHER)
    text = models.TextField(max_length=MAX_LENGTH, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Change request for {self.crag}"

    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    @property
    def requester_name(self):
        return self.requester.username if self.requester else "Someone"


class ChangeRequestMessage(models.Model):
    """A reply in a change request, or its closing step (DONE/DECLINED, with a note)."""

    class Kind(models.TextChoices):
        MESSAGE = "MESSAGE", "Message"
        DONE = "DONE", "Done"
        DECLINED = "DECLINED", "Declined"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    change_request = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MESSAGE)
    text = models.TextField(max_length=ChangeRequest.MAX_LENGTH, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]

    @property
    def author_name(self):
        return self.author.username if self.author else "Someone"


class ChangeRequestPhoto(models.Model):
    """A photo suggested with a change request; private until accepted.

    Accepting copies it into the crag's gallery (crags.views); the suggestion
    and its file are deleted when the request is closed either way.
    """

    change_request = models.ForeignKey(
        ChangeRequest, on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(upload_to=suggested_photo_upload_path)
    category = models.CharField(
        max_length=10, choices=Photo.Category.choices, default=Photo.Category.CRAG
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"Suggested photo for {self.change_request.crag}"


@receiver(post_delete, sender=ChangeRequestPhoto)
def delete_suggested_photo_file(sender, instance, **kwargs):
    """Also on cascades (a deleted crag or request): no orphaned files."""
    if instance.image:
        instance.image.delete(save=False)
