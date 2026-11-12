from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
import uuid

def photo_upload_path(instance, filename):
    # Random name: the user's filename is never used
    return f"crags/{uuid.uuid4().hex}.webp"

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
        Status.DRAFT: {Status.PENDING, Status.REMOVED},
        Status.PENDING: {
            Status.PUBLISHED, Status.NEEDS_CHANGES, Status.REJECTED, Status.REMOVED,
        },
        Status.NEEDS_CHANGES: {Status.PENDING, Status.REMOVED},
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
        if to == self.Status.PENDING:
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
        if to in (self.Status.PUBLISHED, self.Status.NEEDS_CHANGES):
            from .notifications import notify_submitter

            notify_submitter(self)

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

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Photo of {self.crag.name}"


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
