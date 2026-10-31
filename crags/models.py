from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
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


class CragQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Crag.Status.PUBLISHED)

    def public(self):
        return self.filter(status__in=Crag.PUBLIC_STATUSES)


class Crag(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending review"
        PUBLISHED = "PUBLISHED", "Published"
        REJECTED = "REJECTED", "Rejected"
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

    guidebook = models.CharField(max_length=250, blank=True)

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
        max_length=10,
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CragQuerySet.as_manager()

    def clean(self):
        super().clean()
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Latitude and longitude must be provided together.")

    class Meta:
        ordering = ["name"]

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