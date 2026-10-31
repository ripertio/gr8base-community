import io
import re
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import MAX_EDGE, MAX_UPLOAD_BYTES, process_image
from .models import Area, Crag, Feature, Photo

User = get_user_model()


def form_data(base_area, **overrides):
    data = {
        "name": "Testfels",
        "area": base_area.pk,
        "new_area": "",
        "description": "",
        "approach_minutes": "",
        "rating_babies": "",
        "rating_ages_2_4": "",
        "rating_ages_5_plus": "",
        "approach_assessed": "",
        "approach_features": [],
        "base_assessed": "",
        "base_features": [],
        "guidebook": "",
        "location": "",
        "parking": "",
        "family_notes": "",
        "orientation": "",
        "action": "draft",
    }
    data.update(overrides)
    return data


def image_upload(name):
    image_buffer = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(image_buffer, format="JPEG")
    return SimpleUploadedFile(name, image_buffer.getvalue(), content_type="image/jpeg")


class CragTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.area = Area.objects.create(name="Allgau")
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pw-alice-123")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "pw-bob-123")
        cls.staff = User.objects.create_user(
            "staff", "staff@example.com", "pw-staff-123", is_staff=True
        )

        cls.published = Crag.objects.create(
            name="Public", area=cls.area, created_by=cls.alice,
            status=Crag.Status.PUBLISHED,
        )
        cls.draft = Crag.objects.create(
            name="Draft entry", area=cls.area, created_by=cls.alice,
            status=Crag.Status.DRAFT,
        )
        cls.pending = Crag.objects.create(
            name="Waiting", area=cls.area, created_by=cls.alice,
            status=Crag.Status.PENDING,
        )


class PublicVisibilityTests(CragTestBase):
    def test_homepage_displays_crag_list(self):
        resp = self.client.get("/")

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "crags/crag_list.html")
        self.assertContains(resp, "Public")

    def test_list_shows_published_and_pending_but_not_drafts(self):
        resp = self.client.get(reverse("crags:list"))
        self.assertContains(resp, "Public")
        self.assertContains(resp, "Waiting")
        self.assertNotContains(resp, "Draft entry")

    def test_rejected_crag_is_hidden_from_public(self):
        rejected = Crag.objects.create(
            name="Rejected entry", area=self.area, created_by=self.alice,
            status=Crag.Status.REJECTED,
        )
        self.assertNotContains(self.client.get(reverse("crags:list")), "Rejected entry")
        resp = self.client.get(reverse("crags:detail", args=[rejected.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_can_open_pending_detail(self):
        resp = self.client.get(reverse("crags:detail", args=[self.pending.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_list_ignores_bad_filter_input(self):
        resp = self.client.get(reverse("crags:list"), {"rating": "abc", "area": "xyz"})
        self.assertEqual(resp.status_code, 200)

    def test_rating_filter_matches_any_age_group(self):
        self.pending.rating_ages_2_4 = 4
        self.pending.save()

        response = self.client.get(reverse("crags:list"), {"rating": "4"})

        self.assertContains(response, "Waiting")
        self.assertNotContains(response, "Public")

    def test_list_filters_by_area_name(self):
        other_area = Area.objects.create(name="Tannheim Valley")
        Crag.objects.create(
            name="Other crag",
            area=other_area,
            created_by=self.alice,
            status=Crag.Status.PUBLISHED,
        )

        resp = self.client.get(reverse("crags:list"), {"area": self.area.name})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Public")
        self.assertNotContains(resp, "Other crag")
        self.assertEqual(resp.context["selected_area"], self.area.name)
        self.assertContains(resp, f'value="{self.area.name}"')

    def test_anonymous_can_open_published_detail(self):
        resp = self.client.get(reverse("crags:detail", args=[self.published.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_location_link_uses_google_maps_url(self):
        crag = Crag.objects.create(
            name="Crag with location",
            area=self.area,
            created_by=self.alice,
            status=Crag.Status.PUBLISHED,
            latitude="47.123456",
            longitude="10.654321",
        )

        response = self.client.get(reverse("crags:detail", args=[crag.pk]))

        self.assertContains(
            response,
            'href="https://www.google.com/maps/search/?api=1&amp;query=47.123456,10.654321"',
        )

    def test_unassessed_places_show_no_information(self):
        response = self.client.get(reverse("crags:detail", args=[self.published.pk]))

        self.assertContains(response, "No further information")
        self.assertContains(response, "No information", count=1)
        self.assertNotContains(response, "Not stroller-friendly")
        self.assertNotContains(response, "No hazards reported")

    def test_assessed_empty_places_report_no_hazards_and_not_stroller_friendly(self):
        self.published.approach_assessed = True
        self.published.base_assessed = True
        self.published.save()

        response = self.client.get(reverse("crags:detail", args=[self.published.pk]))

        self.assertContains(response, "No hazards reported", count=2)
        self.assertContains(response, "Not stroller-friendly", count=2)
        self.assertNotContains(response, "safe")

    def test_assessed_features_use_warning_and_positive_styles(self):
        rockfall = Feature.objects.get(slug="rockfall")
        stroller_friendly = Feature.objects.get(slug="stroller_friendly")
        fall_hazard = Feature.objects.get(slug="fall_hazard")
        self.published.approach_assessed = True
        self.published.base_assessed = True
        self.published.save()
        self.published.approach_features.add(rockfall, stroller_friendly)
        self.published.base_features.add(fall_hazard)

        response = self.client.get(reverse("crags:detail", args=[self.published.pk]))

        html = response.content.decode()
        self.assertRegex(html, r'class="assessment-warning">\s*Rockfall')
        self.assertRegex(html, r'class="assessment-positive">\s*Stroller-friendly')
        self.assertRegex(html, r'class="assessment-warning">\s*Fall hazard')
        self.assertContains(response, "Not stroller-friendly")
        self.assertNotContains(response, "No hazards reported")

    def test_anonymous_gets_404_for_draft(self):
        resp = self.client.get(reverse("crags:detail", args=[self.draft.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_other_user_gets_404_for_foreign_draft(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("crags:detail", args=[self.draft.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_owner_can_see_own_draft(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("crags:detail", args=[self.draft.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_staff_can_see_any_draft(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("crags:detail", args=[self.draft.pk]))
        self.assertEqual(resp.status_code, 200)


class LoginRequiredTests(CragTestBase):
    def test_anonymous_is_redirected_from_protected_pages(self):
        urls = [
            reverse("crags:create"),
            reverse("crags:mine"),
            reverse("crags:edit", args=[self.published.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/accounts/login/", resp["Location"])


class CragManagersAdminTests(CragTestBase):
    def setUp(self):
        self.bob.is_staff = True
        self.bob.save(update_fields=["is_staff"])
        self.bob.groups.add(Group.objects.get(name="Crag Managers"))
        self.client.force_login(self.bob)

    def test_group_can_manage_other_users_crags_and_areas_in_admin(self):
        urls = [
            reverse("admin:crags_crag_changelist"),
            reverse("admin:crags_crag_add"),
            reverse("admin:crags_crag_change", args=[self.published.pk]),
            reverse("admin:crags_crag_delete", args=[self.published.pk]),
            reverse("admin:crags_area_changelist"),
            reverse("admin:crags_area_add"),
            reverse("admin:crags_area_change", args=[self.area.pk]),
            reverse(
                "admin:crags_area_delete",
                args=[Area.objects.create(name="Unused area").pk],
            ),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_crag_managers_group_does_not_grant_superuser(self):
        self.assertFalse(self.bob.is_superuser)


class EditPermissionTests(CragTestBase):
    def test_edit_form_prefills_existing_location(self):
        crag = Crag.objects.create(
            name="Crag with coordinates",
            area=self.area,
            created_by=self.alice,
            latitude="47.123456",
            longitude="10.654321",
        )
        self.client.force_login(self.alice)

        response = self.client.get(reverse("crags:edit", args=[crag.pk]))

        self.assertEqual(
            response.context["form"]["location"].value(),
            "47.123456, 10.654321",
        )

    def test_other_user_cannot_open_edit_page(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("crags:edit", args=[self.published.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_other_user_cannot_post_edit(self):
        self.client.force_login(self.bob)
        resp = self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(self.area, name="Hacked"),
        )
        self.assertEqual(resp.status_code, 404)
        self.published.refresh_from_db()
        self.assertEqual(self.published.name, "Public")

    def test_owner_can_edit_own_crag(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("crags:edit", args=[self.draft.pk]),
            form_data(self.area, name="Renamed"),
        )
        self.assertEqual(resp.status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.name, "Renamed")

    def test_staff_can_edit_any_crag(self):
        self.client.force_login(self.staff)
        resp = self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(self.area, name="Corrected"),
        )
        self.assertEqual(resp.status_code, 302)
        self.published.refresh_from_db()
        self.assertEqual(self.published.name, "Corrected")
        # staff edits do not change the status
        self.assertEqual(self.published.status, Crag.Status.PUBLISHED)

    def test_editing_published_crag_requires_new_review(self):
        self.client.force_login(self.alice)
        self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(self.area, name="Changed"),
        )
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Crag.Status.PENDING)


class CreateTests(CragTestBase):
    def test_create_draft_sets_owner_and_status(self):
        self.client.force_login(self.bob)
        self.client.post(reverse("crags:create"), form_data(self.area, name="Bobs Crag"))
        crag = Crag.objects.get(name="Bobs Crag")
        self.assertEqual(crag.created_by, self.bob)
        self.assertEqual(crag.status, Crag.Status.DRAFT)

    def test_submit_sets_pending(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="Bobs Crag", action="submit"),
        )
        self.assertEqual(Crag.objects.get(name="Bobs Crag").status, Crag.Status.PENDING)

    def test_user_cannot_inject_status_or_owner(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Cheater",
                status="PUBLISHED",
                created_by=self.alice.pk,
            ),
        )
        crag = Crag.objects.get(name="Cheater")
        self.assertEqual(crag.status, Crag.Status.DRAFT)
        self.assertEqual(crag.created_by, self.bob)

    def test_create_form_includes_optional_photo_upload(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("crags:create"))

        self.assertContains(response, 'name="images"')
        self.assertContains(response, "Add photos (optional)")
        self.assertContains(response, '<select name="rating_babies"')
        self.assertContains(response, "Rating for babies")
        self.assertContains(response, "Use my current location")
        self.assertContains(response, 'data-location-status role="status"')

    def test_age_ratings_save_selected_values(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Rated crag",
                rating_babies="2",
                rating_ages_2_4="3",
                rating_ages_5_plus="4",
            ),
        )

        crag = Crag.objects.get(name="Rated crag")
        self.assertEqual(crag.rating_babies, 2)
        self.assertEqual(crag.rating_ages_2_4, 3)
        self.assertEqual(crag.rating_ages_5_plus, 4)

    def test_selected_features_save_and_mark_places_assessed(self):
        self.client.force_login(self.bob)
        rockfall = Feature.objects.get(slug="rockfall")
        stroller_friendly = Feature.objects.get(slug="stroller_friendly")
        response = self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Features entered",
                approach_features=[str(rockfall.pk)],
                base_features=[str(stroller_friendly.pk)],
            ),
        )

        self.assertEqual(response.status_code, 302)
        crag = Crag.objects.get(name="Features entered")
        self.assertTrue(crag.approach_assessed)
        self.assertTrue(crag.base_assessed)
        self.assertEqual(list(crag.approach_features.all()), [rockfall])
        self.assertEqual(list(crag.base_features.all()), [stroller_friendly])

    def test_assessment_checkboxes_save_without_features(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Empty rating",
                approach_assessed="on",
                base_assessed="on",
            ),
        )

        crag = Crag.objects.get(name="Empty rating")
        self.assertTrue(crag.approach_assessed)
        self.assertTrue(crag.base_assessed)

    def test_malformed_coordinates_are_rejected(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Incomplete coordinates",
                location="47.123456",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Crag.objects.filter(name="Incomplete coordinates").exists())
        self.assertContains(response, "Enter coordinates such as")

    def test_google_maps_url_coordinates_are_saved(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Maps link",
                location="https://www.google.com/maps/place/Fels/@47.123456,10.654321,15z",
            ),
        )

        crag = Crag.objects.get(name="Maps link")
        self.assertEqual(str(crag.latitude), "47.123456")
        self.assertEqual(str(crag.longitude), "10.654321")

    def test_google_maps_share_url_coordinates_are_saved(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("crags:create"),
            form_data(
                self.area,
                name="Maps share link",
                location=(
                    "https://www.google.com/maps/place/Fels/"
                    "data=!4m2!3m1!1s0x0!3d47.123456!4d10.654321"
                ),
            ),
        )

        crag = Crag.objects.get(name="Maps share link")
        self.assertEqual(str(crag.latitude), "47.123456")
        self.assertEqual(str(crag.longitude), "10.654321")

    def test_invalid_coordinate_ranges_are_rejected(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="Invalid location", location="91, 10"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Crag.objects.filter(name="Invalid location").exists())
        self.assertContains(response, "Latitude must be between")

    def test_create_crag_with_multiple_photos(self):
        self.client.force_login(self.bob)
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("crags:create"),
                    {
                        **form_data(self.area, name="Crag with photos"),
                        "category": Photo.Category.PARKING,
                        "images": [image_upload("first.jpg"), image_upload("second.jpg")],
                    },
                )

        crag = Crag.objects.get(name="Crag with photos")
        self.assertRedirects(response, reverse("crags:detail", args=[crag.pk]))
        photos = Photo.objects.filter(crag=crag)
        self.assertEqual(photos.count(), 2)
        self.assertEqual(
            set(photos.values_list("category", flat=True)),
            {Photo.Category.PARKING},
        )
        self.assertTrue(all(photo.image.name.endswith(".webp") for photo in photos))

    def test_invalid_photo_prevents_crag_creation(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("crags:create"),
            {
                **form_data(self.area, name="Invalid photo"),
                "category": Photo.Category.CRAG,
                "images": [
                    SimpleUploadedFile(
                        "not-an-image.jpg", b"not an image", content_type="image/jpeg"
                    )
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Crag.objects.filter(name="Invalid photo").exists())
        self.assertContains(response, "The file could not be read as an image.")


class NewAreaTests(CragTestBase):
    def setUp(self):
        self.client.force_login(self.bob)

    def test_new_area_is_created(self):
        self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", area="", new_area="Tannheim Valley"),
        )
        self.assertEqual(Crag.objects.get(name="New").area.name, "Tannheim Valley")

    def test_new_area_reuses_existing_name_case_insensitive(self):
        self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", area="", new_area="  allgau "),
        )
        self.assertEqual(Area.objects.filter(name__iexact="allgau").count(), 1)
        self.assertEqual(Crag.objects.get(name="New").area, self.area)

    def test_both_empty_is_rejected(self):
        resp = self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", area="", new_area=""),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Crag.objects.filter(name="New").exists())

    def test_both_filled_is_rejected(self):
        resp = self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", new_area="Other area"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Crag.objects.filter(name="New").exists())


class PhotoUploadTests(CragTestBase):
    def test_crag_detail_renders_gallery_with_direct_image_fallback(self):
        self.client.force_login(self.alice)
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                photo = Photo.objects.create(
                    crag=self.draft,
                    image=image_upload("gallery.jpg"),
                    category=Photo.Category.CRAG,
                    uploaded_by=self.alice,
                )
                response = self.client.get(reverse("crags:detail", args=[self.draft.pk]))

        self.assertContains(response, 'class="gallery-trigger"')
        self.assertContains(response, 'href="/media/%s"' % photo.image.name)
        self.assertContains(response, 'dialog class="photo-gallery"')
        self.assertContains(response, "data-gallery-next")
        self.assertContains(response, "/static/js/photo-gallery.")

    def test_owner_can_upload_multiple_photos(self):
        image_buffer = io.BytesIO()
        Image.new("RGB", (32, 24), "red").save(image_buffer, format="JPEG")
        image_bytes = image_buffer.getvalue()

        self.client.force_login(self.alice)
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("crags:photo_add", args=[self.draft.pk]),
                    {
                        "category": Photo.Category.CRAG,
                        "images": [
                            SimpleUploadedFile(
                                "first.jpg", image_bytes, content_type="image/jpeg"
                            ),
                            SimpleUploadedFile(
                                "second.jpg", image_bytes, content_type="image/jpeg"
                            ),
                        ],
                    },
                )

        self.assertRedirects(response, reverse("crags:detail", args=[self.draft.pk]))
        photos = Photo.objects.filter(crag=self.draft).order_by("pk")
        self.assertEqual(photos.count(), 2)
        self.assertTrue(all(photo.image.name.endswith(".webp") for photo in photos))

class ProcessImageTests(SimpleTestCase):
    def _jpeg(self, size=(32, 24), exif=None):
        buffer = io.BytesIO()
        Image.new("RGB", size, "red").save(buffer, format="JPEG", exif=exif or b"")
        return SimpleUploadedFile("photo.jpg", buffer.getvalue(), content_type="image/jpeg")

    def test_exif_metadata_is_removed(self):
        exif = Image.Exif()
        exif[0x010F] = "Test Camera Make"  # Make tag
        content = process_image(self._jpeg(exif=exif.tobytes()))

        result = Image.open(io.BytesIO(content.read()))
        self.assertEqual(len(result.getexif()), 0)
        self.assertNotIn("exif", result.info)

    def test_large_image_is_resized_and_keeps_aspect_ratio(self):
        content = process_image(self._jpeg(size=(3000, 2000)))

        result = Image.open(io.BytesIO(content.read()))
        self.assertEqual(max(result.size), MAX_EDGE)
        self.assertAlmostEqual(result.width / result.height, 1.5, places=2)

    def test_small_image_is_not_upscaled(self):
        content = process_image(self._jpeg(size=(32, 24)))

        result = Image.open(io.BytesIO(content.read()))
        self.assertEqual(result.size, (32, 24))

    def test_output_is_webp(self):
        content = process_image(self._jpeg(size=(800, 600)))

        result = Image.open(io.BytesIO(content.read()))
        self.assertEqual(result.format, "WEBP")

    def test_oversized_file_is_rejected(self):
        upload = SimpleUploadedFile(
            "big.jpg", b"0" * (MAX_UPLOAD_BYTES + 1), content_type="image/jpeg"
        )
        with self.assertRaisesMessage(ValidationError, "too large"):
            process_image(upload)

    def test_non_image_content_is_rejected(self):
        upload = SimpleUploadedFile("evil.jpg", b"not an image", content_type="image/jpeg")
        with self.assertRaisesMessage(ValidationError, "could not be read"):
            process_image(upload)

    def test_disallowed_format_is_rejected(self):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buffer, format="BMP")
        upload = SimpleUploadedFile("photo.bmp", buffer.getvalue(), content_type="image/bmp")
        with self.assertRaisesMessage(ValidationError, "Please upload"):
            process_image(upload)
