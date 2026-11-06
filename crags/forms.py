import io
import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
import pillow_heif

from .models import Area, Crag, Feature, Guidebook, Photo

pillow_heif.register_heif_opener()

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024   # 15 MB
MAX_PIXELS = 60_000_000               # protects against decompression bombs
MAX_EDGE = 1600                       # longest side after resize
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO", "HEIF"}
RATING_CHOICES = [
    ("", "– Please select –"),
    (1, "★ 1/5"),
    (2, "★ 2/5"),
    (3, "★ 3/5"),
    (4, "★ 4/5"),
    (5, "★ 5/5"),
]
COORDINATE_PAIR_RE = re.compile(
    r"(?P<latitude>[+-]?\d{1,2}(?:\.\d+)?)\s*,\s*"
    r"(?P<longitude>[+-]?\d{1,3}(?:\.\d+)?)"
)
GOOGLE_MAPS_COORDINATES_RE = re.compile(
    r"!3d(?P<latitude>[+-]?\d+(?:\.\d+)?)"
    r"!4d(?P<longitude>[+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_coordinates(value):
    """Extract latitude and longitude from decimal coordinates or a Maps URL."""
    value = (value or "").strip()
    if not value:
        return None, None

    match = GOOGLE_MAPS_COORDINATES_RE.search(value)
    if match is None:
        match = COORDINATE_PAIR_RE.search(value)
    if match is None:
        raise ValidationError(
            "Enter coordinates such as “47.123456, 10.123456” or a full "
            "Google Maps link."
        )

    try:
        latitude = Decimal(match.group("latitude"))
        longitude = Decimal(match.group("longitude"))
        precision = Decimal("0.000001")
        latitude = latitude.quantize(precision, rounding=ROUND_HALF_UP)
        longitude = longitude.quantize(precision, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValidationError("The coordinates are invalid or too precise.")

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValidationError(
            "Latitude must be between −90 and 90 and longitude between −180 and 180."
        )

    return latitude, longitude


def process_image(upload, max_edge=MAX_EDGE):
    """Validate an upload and return it as a resized WEBP ContentFile."""
    if upload.size > MAX_UPLOAD_BYTES:
        logger.warning("image rejected: too large")
        raise ValidationError("The image is too large (maximum 15 MB).")

    try:
        upload.seek(0)
        img = Image.open(upload)
        if img.format not in ALLOWED_FORMATS:
            logger.warning("image rejected: format %s", img.format)
            raise ValidationError(
                "Please upload a JPG, PNG, WebP, or HEIC image."
            )
        if img.width * img.height > MAX_PIXELS:
            logger.warning("image rejected: too many pixels")
            raise ValidationError("The image has too many pixels.")

        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((max_edge, max_edge))

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=80, method=4)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        # Only the exception type: its message can contain the uploaded file name.
        logger.warning("image rejected: unreadable (%s)", type(exc).__name__)
        raise ValidationError("The file could not be read as an image.")

    return ContentFile(buffer.getvalue(), name="photo.webp")


class BulkPhotoForm(forms.Form):
    category = forms.ChoiceField(
        choices=Photo.Category.choices,
        initial=Photo.Category.CRAG,
        label="Category",
    )


class CragForm(forms.ModelForm):
    location = forms.CharField(
        required=False,
        label="Crag coordinates",
        help_text=(
            "Google Maps link or coordinates, e.g. 47.123456, 10.123456. "
            "Short links are not supported."
        ),
    )
    parking = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label="Parking",
        help_text="Parking details or a map link.",
    )
    rating_babies = forms.TypedChoiceField(
        choices=RATING_CHOICES, coerce=int, empty_value=None, required=False,
        label="Rating for babies (0–1 years)",
    )
    rating_ages_2_4 = forms.TypedChoiceField(
        choices=RATING_CHOICES, coerce=int, empty_value=None, required=False,
        label="Rating for children (2–4 years)",
    )
    rating_ages_5_plus = forms.TypedChoiceField(
        choices=RATING_CHOICES, coerce=int, empty_value=None, required=False,
        label="Rating for children aged 5 and older",
    )
    approach_assessed = forms.BooleanField(
        required=False,
        label="I have assessed the approach",
    )
    approach_features = forms.ModelMultipleChoiceField(
        queryset=Feature.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="",
    )
    base_assessed = forms.BooleanField(
        required=False,
        label="I have assessed the base",
    )
    base_features = forms.ModelMultipleChoiceField(
        queryset=Feature.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="",
    )
    new_area = forms.CharField(
        max_length=200,
        required=False,
        label="Or add a new area",
        help_text="Only fill this in if the area is not listed above.",
    )
    guidebooks = forms.ModelMultipleChoiceField(
        queryset=Guidebook.objects.all(),
        required=False,
        label="Guidebooks",
        help_text="Search and pick guidebooks that describe this crag, or add a new one.",
    )
    new_guidebook = forms.CharField(
        max_length=250,
        required=False,
        label="Name",
    )
    new_guidebook_url = forms.URLField(
        required=False, label="Link (optional)"
    )
    new_guidebook_publisher = forms.CharField(
        max_length=200, required=False, label="Publisher (optional)"
    )
    new_guidebook_year = forms.IntegerField(
        min_value=1800, max_value=2100, required=False,
        label="Publication year (optional)",
    )
    new_guidebook_picture = forms.ImageField(
        required=False, label="Cover picture (optional)"
    )

    field_order = [
        "name",
        "area",
        "new_area",
        "guidebooks",
        "new_guidebook",
        "new_guidebook_url",
        "new_guidebook_publisher",
        "new_guidebook_year",
        "new_guidebook_picture",
        "description",
        "approach_minutes",
        "approach_assessed",
        "approach_features",
        "base_assessed",
        "base_features",
        "rating_babies",
        "rating_ages_2_4",
        "rating_ages_5_plus",
        "location",
        "parking",
        "family_notes",
        "orientation",
    ]

    class Meta:
        model = Crag
        fields = [
            "name",
            "area",
            "guidebooks",
            "description",
            "approach_minutes",
            "approach_assessed",
            "approach_features",
            "base_assessed",
            "base_features",
            "rating_babies",
            "rating_ages_2_4",
            "rating_ages_5_plus",
            "parking",
            "family_notes",
            "orientation",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._new_area_name = ""
        self._new_guidebook_name = ""
        self._new_guidebook_picture = None
        self._coordinates = (None, None)
        if self.instance and self.instance.pk:
            latitude, longitude = self.instance.latitude, self.instance.longitude
            if latitude is not None and longitude is not None:
                self.fields["location"].initial = f"{latitude}, {longitude}"

        # Either the dropdown or the text field is enough, so neither is required alone.
        # The clean() method below enforces "exactly one of them".
        self.fields["parking"].widget.attrs["rows"] = 5
        self.fields["family_notes"].widget.attrs["rows"] = 5

        self.fields["area"].required = False
        self.fields["area"].empty_label = "– Please select –"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("approach_features"):
            cleaned["approach_assessed"] = True
        if cleaned.get("base_features"):
            cleaned["base_assessed"] = True

        try:
            self._coordinates = parse_coordinates(cleaned.get("location"))
        except ValidationError as exc:
            self.add_error("location", exc)

        # collapse repeated spaces: "Neue   Wand" -> "Neue Wand"
        self._new_area_name = " ".join((cleaned.get("new_area") or "").split())
        area = cleaned.get("area")

        if self._new_area_name and area:
            self.add_error(
                "new_area",
                "Select an area or enter a new one, not both.",
            )
        elif not self._new_area_name and not area:
            self.add_error(
                "area",
                "Select an area or enter a new one.",
            )

        self._new_guidebook_name = " ".join(
            (cleaned.get("new_guidebook") or "").split()
        )
        details = (
            "new_guidebook_url",
            "new_guidebook_publisher",
            "new_guidebook_year",
            "new_guidebook_picture",
        )
        if not self._new_guidebook_name and any(cleaned.get(f) for f in details):
            self.add_error("new_guidebook", "Enter the name of the new guidebook.")
        elif self._new_guidebook_name and cleaned.get("new_guidebook_picture"):
            try:
                self._new_guidebook_picture = process_image(
                    cleaned["new_guidebook_picture"], max_edge=800
                )
            except ValidationError as exc:
                self.add_error("new_guidebook_picture", exc)
        return cleaned

    def _create_new_guidebook(self):
        """Return the guidebook named in the "add new" block, creating it if needed."""
        if not self._new_guidebook_name:
            return None
        guidebook = Guidebook.objects.filter(
            name__iexact=self._new_guidebook_name
        ).first()
        if guidebook is None:
            guidebook = Guidebook(
                name=self._new_guidebook_name,
                url=self.cleaned_data.get("new_guidebook_url") or "",
                publisher=self.cleaned_data.get("new_guidebook_publisher") or "",
                publish_year=self.cleaned_data.get("new_guidebook_year"),
            )
            if self._new_guidebook_picture:
                guidebook.picture.save(
                    "cover.webp", self._new_guidebook_picture, save=False
                )
            guidebook.save()
        return guidebook

    def save(self, commit=True):
        crag = super().save(commit=False)
        crag.latitude, crag.longitude = self._coordinates

        # The view calls save(commit=False) and save_m2m() itself, once the
        # crag exists, so the new guidebook must be linked from there.
        save_selected = self.save_m2m

        def save_m2m():
            save_selected()
            guidebook = self._create_new_guidebook()
            if guidebook is not None:
                crag.guidebooks.add(guidebook)

        self.save_m2m = save_m2m

        if self._new_area_name:
            area = Area.objects.filter(name__iexact=self._new_area_name).first()
            if area is None:
                area = Area.objects.create(name=self._new_area_name)
            crag.area = area

        if commit:
            crag.save()
            self.save_m2m()
        return crag