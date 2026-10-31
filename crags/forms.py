import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
import pillow_heif

from .models import Area, Crag, Feature, Photo

pillow_heif.register_heif_opener()

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
        raise ValidationError("The image is too large (maximum 15 MB).")

    try:
        upload.seek(0)
        img = Image.open(upload)
        if img.format not in ALLOWED_FORMATS:
            raise ValidationError(
                "Please upload a JPG, PNG, WebP, or HEIC image."
            )
        if img.width * img.height > MAX_PIXELS:
            raise ValidationError("The image has too many pixels.")

        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((max_edge, max_edge))

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=80, method=4)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("The file could not be read as an image.")

    return ContentFile(buffer.getvalue(), name="photo.webp")


class BulkPhotoForm(forms.Form):
    category = forms.ChoiceField(
        choices=Photo.Category.choices,
        initial=Photo.Category.CRAG,
        label="Category",
    )


class CragForm(forms.ModelForm):
    guidebook = forms.CharField(
        max_length=250, required=False, label="Guidebook"
    )
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

    field_order = [
        "name",
        "area",
        "new_area",
        "guidebook",
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
            "guidebook",
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
        return cleaned

    def save(self, commit=True):
        crag = super().save(commit=False)
        crag.latitude, crag.longitude = self._coordinates

        if self._new_area_name:
            area = Area.objects.filter(name__iexact=self._new_area_name).first()
            if area is None:
                area = Area.objects.create(name=self._new_area_name)
            crag.area = area

        if commit:
            crag.save()
        return crag