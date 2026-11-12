import io
import re
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image

from .forms import MAX_EDGE, MAX_UPLOAD_BYTES, process_image
from .models import Area, Crag, InvalidTransition, CragComment, CragRating, Feature, Guidebook, Photo


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

    def test_list_filters_by_age_orientation_and_approach(self):
        self.published.rating_babies = 5
        self.published.orientation = "S"
        self.published.approach_minutes = 10
        self.published.save()
        url = reverse("crags:list")

        resp = self.client.get(url, {"age": "babies", "rating": "4"})
        self.assertContains(resp, "Public")
        self.assertNotContains(resp, "Waiting")

        resp = self.client.get(url, {"orientation": "S"})
        self.assertContains(resp, "Public")
        self.assertNotContains(resp, "Waiting")

        resp = self.client.get(url, {"max_approach": "10"})
        self.assertContains(resp, "Public")
        self.assertNotContains(resp, "Waiting")

        resp = self.client.get(url, {"max_approach": "5"})
        self.assertNotContains(resp, "Public")

    def test_list_filters_by_features(self):
        stroller = Feature.objects.get(slug="stroller_friendly")
        rockfall = Feature.objects.get(slug="rockfall")
        self.published.approach_features.add(stroller)
        self.pending.approach_features.add(rockfall)
        url = reverse("crags:list")

        resp = self.client.get(url, {"stroller_approach": "1"})
        self.assertContains(resp, "Public")
        self.assertNotContains(resp, "Waiting")

        resp = self.client.get(url, {"avoid": "rockfall"})
        self.assertContains(resp, "Public")
        self.assertNotContains(resp, "Waiting")
        self.assertEqual(resp.context["active_filters"], 1)

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
        self.assertContains(response, "No information", count=2)
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
        self.assertRegex(html, r'class="chip chip-bad">\s*Rockfall')
        self.assertRegex(html, r'class="chip chip-good">\s*Stroller-friendly')
        self.assertRegex(html, r'class="chip chip-bad">\s*Fall hazard')
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

    def test_group_cannot_hard_delete_or_restore_but_can_publish_and_remove(self):
        self.assertEqual(
            self.client.get(
                reverse("admin:crags_crag_delete", args=[self.published.pk])
            ).status_code,
            403,
        )
        self.assertTrue(self.bob.has_perm("crags.can_publish_crag"))
        self.assertTrue(self.bob.has_perm("crags.can_remove_crag"))
        self.assertFalse(self.bob.has_perm("crags.delete_crag"))
        actions = self.client.get(reverse("admin:crags_crag_changelist")).context[
            "action_form"
        ].fields["action"].choices
        self.assertNotIn("restore", [value for value, _ in actions])

    def test_group_can_manage_guidebooks_in_admin(self):
        book = Guidebook.objects.create(name="Admin Book")
        urls = [
            reverse("admin:crags_guidebook_changelist"),
            reverse("admin:crags_guidebook_add"),
            reverse("admin:crags_guidebook_change", args=[book.pk]),
            reverse("admin:crags_guidebook_delete", args=[book.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_guidebook_with_name_only(self):
        resp = self.client.post(
            reverse("admin:crags_guidebook_add"), {"name": "Only Name"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Guidebook.objects.filter(name="Only Name").exists())

    def test_admin_guidebook_requires_name(self):
        resp = self.client.post(reverse("admin:crags_guidebook_add"), {"name": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Guidebook.objects.exists())

    def test_admin_guidebook_picture_is_reencoded_to_webp(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            resp = self.client.post(
                reverse("admin:crags_guidebook_add"),
                {"name": "Pic", "picture": image_upload("cover.jpg")},
            )
            self.assertEqual(resp.status_code, 302)
            book = Guidebook.objects.get(name="Pic")
            self.assertTrue(book.picture.name.endswith(".webp"))
            self.assertNotIn("cover", book.picture.name)

    def test_admin_guidebook_rejects_non_image(self):
        resp = self.client.post(
            reverse("admin:crags_guidebook_add"),
            {
                "name": "Bad",
                "picture": SimpleUploadedFile("x.jpg", b"not an image", "image/jpeg"),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Guidebook.objects.exists())

    def test_crag_managers_group_does_not_grant_superuser(self):
        self.assertFalse(self.bob.is_superuser)


class RemoveCragTests(CragTestBase):
    def remove(self, user, crag):
        self.client.force_login(user)
        return self.client.post(reverse("crags:delete", args=[crag.pk]))

    def test_owner_removal_is_soft(self):
        self.assertEqual(self.remove(self.alice, self.draft).status_code, 302)
        self.assertFalse(Crag.objects.filter(pk=self.draft.pk).exists())
        self.assertEqual(
            Crag.all_objects.get(pk=self.draft.pk).status, Crag.Status.REMOVED
        )

    def test_removed_crag_is_hidden_everywhere(self):
        self.remove(self.alice, self.published)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("crags:list")), self.published.name)
        detail = reverse("crags:detail", args=[self.published.pk])
        for user in (None, self.alice, self.staff):
            if user:
                self.client.force_login(user)
            self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertNotContains(self.client.get(reverse("crags:mine")), self.published.name)

    def test_other_users_and_plain_staff_cannot_remove(self):
        for user in (self.bob, self.staff):
            self.assertEqual(self.remove(user, self.draft).status_code, 404)
        self.assertTrue(Crag.objects.filter(pk=self.draft.pk).exists())

    def test_user_with_permission_can_remove_any_crag(self):
        manager = User.objects.create_user("mgr", "m@example.com", "pw", is_staff=True)
        manager.groups.add(Group.objects.get(name="Crag Managers"))
        self.assertEqual(self.remove(manager, self.published).status_code, 302)
        self.assertEqual(
            Crag.all_objects.get(pk=self.published.pk).status, Crag.Status.REMOVED
        )

    def test_edit_form_shows_remove_button_only_with_right(self):
        url = reverse("crags:edit", args=[self.draft.pk])
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(url), "Remove crag")
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(url), "Remove crag")

    def test_removed_crags_only_in_admin_and_restore_is_superuser_only(self):
        self.remove(self.alice, self.published)
        changelist = reverse("admin:crags_crag_changelist")
        listed = lambda: list(self.client.get(changelist).context["cl"].result_list)

        manager = User.objects.create_user("mgr", "m@example.com", "pw", is_staff=True)
        manager.groups.add(Group.objects.get(name="Crag Managers"))
        self.client.force_login(manager)
        self.assertIn(self.published, listed())
        actions = self.client.get(changelist).context["action_form"].fields["action"].choices
        self.assertNotIn("restore", [value for value, _ in actions])

        root = User.objects.create_superuser("root", "r@example.com", "pw")
        self.client.force_login(root)
        self.client.post(
            changelist, {"action": "restore", "_selected_action": [self.published.pk]}
        )
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Crag.Status.DRAFT)
        self.assertTrue(Crag.objects.filter(pk=self.published.pk).exists())


class SuperuserChangeStatusTests(CragTestBase):
    def change(self, user, crag, status, reason=""):
        self.client.force_login(user)
        return self.client.post(
            reverse("admin:crags_crag_changelist"),
            {
                "action": "change_status",
                "_selected_action": [crag.pk],
                "apply": "1",
                "status": status,
                "reason": reason,
            },
        )

    def test_superuser_can_set_any_status_from_any_status(self):
        root = User.objects.create_superuser("root", "r@example.com", "pw")
        statuses = [s.value for s in Crag.Status]
        for source in statuses:
            for target in statuses:
                if source == target:
                    continue
                Crag.all_objects.filter(pk=self.draft.pk).update(status=source)
                reason = "Please fix the parking info." if target == "NEEDS_CHANGES" else ""
                self.change(root, self.draft, target, reason)
                self.assertEqual(
                    Crag.all_objects.get(pk=self.draft.pk).status, target,
                    f"{source} -> {target}",
                )

    def test_needs_changes_requires_a_reason(self):
        root = User.objects.create_superuser("root", "r@example.com", "pw")
        self.change(root, self.published, "NEEDS_CHANGES", "short")
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Crag.Status.PUBLISHED)

    def test_crag_manager_does_not_get_the_action(self):
        manager = User.objects.create_user("mgr", "m@example.com", "pw", is_staff=True)
        manager.groups.add(Group.objects.get(name="Crag Managers"))
        self.change(manager, self.published, "DRAFT")
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Crag.Status.PUBLISHED)


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

    def test_staff_can_edit_any_crag_but_published_goes_back_to_review(self):
        self.client.force_login(self.staff)
        resp = self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(self.area, name="Corrected"),
        )
        self.assertEqual(resp.status_code, 302)
        self.published.refresh_from_db()
        self.assertEqual(self.published.name, "Corrected")
        # plain staff cannot publish, so the change is reviewed again
        self.assertEqual(self.published.status, Crag.Status.PENDING)

    def test_crag_manager_edit_keeps_published_status(self):
        manager = User.objects.create_user("mgr", "m@example.com", "pw", is_staff=True)
        manager.groups.add(Group.objects.get(name="Crag Managers"))
        self.client.force_login(manager)
        self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(self.area, name="Corrected"),
        )
        self.published.refresh_from_db()
        self.assertEqual(self.published.name, "Corrected")
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


class GuidebookDetailTests(CragTestBase):
    def test_detail_lists_guidebooks_with_link_and_meta(self):
        linked = Guidebook.objects.create(
            name="Linked Book", url="https://example.com/b",
            publisher="Panico", publish_year=2021,
        )
        plain = Guidebook.objects.create(name="Plain Book")
        self.published.guidebooks.add(linked, plain)
        resp = self.client.get(reverse("crags:detail", args=[self.published.pk]))
        self.assertContains(resp, 'href="https://example.com/b"')
        self.assertContains(resp, "Panico, 2021")
        self.assertContains(resp, "Plain Book")
        self.assertNotContains(resp, "2,021")

    def test_detail_without_guidebooks_has_no_section(self):
        resp = self.client.get(reverse("crags:detail", args=[self.published.pk]))
        self.assertNotContains(resp, "<h2>Guidebooks</h2>")

    def test_detail_query_count_does_not_grow_with_guidebooks(self):
        url = reverse("crags:detail", args=[self.published.pk])
        self.published.guidebooks.add(Guidebook.objects.create(name="B0"))
        with CaptureQueriesContext(connection) as one:
            self.client.get(url)
        for i in range(1, 4):
            self.published.guidebooks.add(Guidebook.objects.create(name=f"B{i}"))
        with CaptureQueriesContext(connection) as four:
            self.client.get(url)
        self.assertEqual(len(one), len(four))


class GuidebookFormTests(CragTestBase):
    def setUp(self):
        self.client.force_login(self.bob)

    def test_select_several_existing_guidebooks(self):
        a = Guidebook.objects.create(name="Book A")
        b = Guidebook.objects.create(name="Book B")
        self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", guidebooks=[a.pk, b.pk]),
        )
        self.assertEqual(set(Crag.objects.get(name="New").guidebooks.all()), {a, b})

    def test_one_guidebook_on_several_crags(self):
        book = Guidebook.objects.create(name="Shared")
        for name in ("One", "Two"):
            self.client.post(
                reverse("crags:create"),
                form_data(self.area, name=name, guidebooks=[book.pk]),
            )
        self.assertEqual(book.crags.count(), 2)

    def test_new_guidebook_with_name_only(self):
        self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", new_guidebook="Fresh Book"),
        )
        book = Guidebook.objects.get(name="Fresh Book")
        self.assertEqual(book.url, "")
        self.assertIsNone(book.publish_year)
        self.assertFalse(book.picture)
        self.assertIn(book, Crag.objects.get(name="New").guidebooks.all())

    def test_new_guidebook_with_all_details(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.client.post(
                reverse("crags:create"),
                form_data(
                    self.area,
                    name="New",
                    new_guidebook="Full Book",
                    new_guidebook_url="https://example.com/book",
                    new_guidebook_publisher="Panico",
                    new_guidebook_year="2021",
                    new_guidebook_picture=image_upload("cover.jpg"),
                ),
            )
            book = Guidebook.objects.get(name="Full Book")
            self.assertEqual(book.url, "https://example.com/book")
            self.assertEqual(book.publisher, "Panico")
            self.assertEqual(book.publish_year, 2021)
            self.assertTrue(book.picture.name.endswith(".webp"))

    def test_new_guidebook_added_on_edit_keeps_existing_ones(self):
        old = Guidebook.objects.create(name="Old")
        self.published.guidebooks.add(old)
        self.published.created_by = self.bob
        self.published.save()
        self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(
                self.area, name="Public", guidebooks=[old.pk], new_guidebook="Extra"
            ),
        )
        names = set(self.published.guidebooks.values_list("name", flat=True))
        self.assertEqual(names, {"Old", "Extra"})

    def test_new_guidebook_reuses_existing_name_case_insensitive(self):
        Guidebook.objects.create(name="Panico Pfalz")
        self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", new_guidebook=" panico   pfalz "),
        )
        self.assertEqual(Guidebook.objects.count(), 1)
        self.assertEqual(Crag.objects.get(name="New").guidebooks.count(), 1)

    def test_details_without_name_are_rejected(self):
        resp = self.client.post(
            reverse("crags:create"),
            form_data(self.area, name="New", new_guidebook_publisher="Panico"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Crag.objects.filter(name="New").exists())

    def test_invalid_year_is_rejected(self):
        resp = self.client.post(
            reverse("crags:create"),
            form_data(
                self.area, name="New", new_guidebook="Book", new_guidebook_year="1200"
            ),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Guidebook.objects.exists())


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


class EventLoggingTests(CragTestBase):
    """Events are logged with IDs only: no names, emails or filenames."""

    def assertNoPersonalData(self, logs, *values):
        output = "\n".join(logs.output)
        for value in values:
            self.assertNotIn(value, output)

    def test_create_logs_ids_only(self):
        self.client.force_login(self.bob)
        with self.assertLogs("crags.views", "INFO") as logs:
            self.client.post(
                reverse("crags:create"), form_data(self.area, name="Secret Name")
            )
        crag = Crag.objects.get(name="Secret Name")
        self.assertIn(
            f"crag created id={crag.pk} user={self.bob.pk} status={Crag.Status.DRAFT.value}", logs.output[0]
        )
        self.assertNoPersonalData(logs, "Secret Name", "bob", "example.com")

    def test_create_with_photos_logs_upload(self):
        self.client.force_login(self.bob)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with self.assertLogs("crags.views", "INFO") as logs:
                self.client.post(
                    reverse("crags:create"),
                    {
                        **form_data(self.area, name="With photo"),
                        "category": Photo.Category.CRAG,
                        "images": [image_upload("holiday-secret.jpg")],
                    },
                )
        crag = Crag.objects.get(name="With photo")
        self.assertTrue(
            any(
                f"photos uploaded crag={crag.pk} user={self.bob.pk} count=1" in line
                for line in logs.output
            )
        )
        self.assertNoPersonalData(logs, "holiday-secret", "With photo")

    def test_failed_create_logs_no_creation(self):
        self.client.force_login(self.bob)
        with self.assertNoLogs("crags.views", "INFO"):
            self.client.post(
                reverse("crags:create"),
                {
                    **form_data(self.area, name="Invalid photo"),
                    "category": Photo.Category.CRAG,
                    "images": [
                        SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
                    ],
                },
            )

    def test_edit_logs_update(self):
        self.client.force_login(self.alice)
        with self.assertLogs("crags.views", "INFO") as logs:
            self.client.post(
                reverse("crags:edit", args=[self.draft.pk]),
                form_data(self.area, name="Renamed"),
            )
        self.assertIn(
            f"crag updated id={self.draft.pk} user={self.alice.pk} status={Crag.Status.DRAFT.value}",
            logs.output[0],
        )
        self.assertNoPersonalData(logs, "Renamed", "Draft entry")

    def test_remove_logs_removal(self):
        self.client.force_login(self.alice)
        pk = self.draft.pk
        with self.assertLogs("crags.views", "INFO") as logs:
            self.client.post(reverse("crags:delete", args=[pk]))
        self.assertIn(f"crag removed id={pk} user={self.alice.pk}", logs.output[0])
        self.assertNoPersonalData(logs, "Draft entry")

    def test_photo_delete_logs_deletion(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            photo = Photo.objects.create(
                crag=self.draft,
                image=process_image(image_upload("a.jpg")),
                category=Photo.Category.CRAG,
                uploaded_by=self.alice,
            )
            self.client.force_login(self.alice)
            with self.assertLogs("crags.views", "INFO") as logs:
                self.client.post(reverse("crags:photo_delete", args=[photo.pk]))
        self.assertIn(
            f"photo deleted id={photo.pk} crag={self.draft.pk} user={self.alice.pk}",
            logs.output[0],
        )

    def test_rejected_images_log_the_reason(self):
        cases = {
            "too large": SimpleUploadedFile("a.jpg", b"0" * (MAX_UPLOAD_BYTES + 1)),
            "unreadable": SimpleUploadedFile("private-name.jpg", b"not an image"),
        }
        bmp = io.BytesIO()
        Image.new("RGB", (8, 8)).save(bmp, format="BMP")
        cases["format"] = SimpleUploadedFile("a.bmp", bmp.getvalue())

        for reason, upload in cases.items():
            with self.subTest(reason=reason):
                with self.assertLogs("crags.forms", "WARNING") as logs:
                    with self.assertRaises(ValidationError):
                        process_image(upload)
                self.assertIn(f"image rejected: {reason}", logs.output[0])
                self.assertNoPersonalData(logs, "private-name")



class CommunityRatingTests(CragTestBase):
    def url(self, crag=None):
        return reverse("crags:rate", args=[(crag or self.published).pk])

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(self.url(), {"rating_babies": "3"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CragRating.objects.count(), 0)

    def test_author_cannot_rate_own_crag(self):
        self.client.login(username="alice", password="pw-alice-123")
        self.client.post(self.url(), {"rating_babies": "3"})
        self.assertEqual(CragRating.objects.count(), 0)

    def test_cannot_rate_unpublished_crag(self):
        self.client.login(username="bob", password="pw-bob-123")
        response = self.client.post(self.url(self.pending), {"rating_babies": "3"})
        self.assertEqual(response.status_code, 404)

    def test_rating_is_saved_and_updated(self):
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(self.url(), {"rating_babies": "3", "rating_ages_2_4": "5"})
        self.client.post(self.url(), {"rating_babies": "4", "rating_ages_2_4": ""})
        rating = CragRating.objects.get()
        self.assertEqual(rating.rating_babies, 4)
        self.assertIsNone(rating.rating_ages_2_4)

    def test_invalid_score_is_rejected(self):
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(self.url(), {"rating_babies": "9"})
        self.assertEqual(CragRating.objects.count(), 0)

    def test_empty_submission_removes_rating(self):
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(self.url(), {"rating_babies": "3"})
        self.client.post(self.url(), {})
        self.assertEqual(CragRating.objects.count(), 0)

    def test_detail_shows_average_per_age(self):
        CragRating.objects.create(crag=self.published, user=self.bob, rating_babies=4)
        CragRating.objects.create(crag=self.published, user=self.staff, rating_babies=5)
        response = self.client.get(reverse("crags:detail", args=[self.published.pk]))
        self.assertContains(response, "★ 4.5/5 (2)")

    def test_list_shows_community_average_in_brackets(self):
        self.published.rating_babies = 4
        self.published.save()
        CragRating.objects.create(crag=self.published, user=self.bob, rating_babies=3)
        CragRating.objects.create(crag=self.published, user=self.staff, rating_babies=4)
        response = self.client.get(reverse("crags:list"))
        self.assertContains(response, "Babies: ★ 4/5 (3.5)")


class CragCommentTests(CragTestBase):
    def add_url(self, crag=None):
        return reverse("crags:comment_add", args=[(crag or self.published).pk])

    def test_anonymous_cannot_comment(self):
        response = self.client.post(self.add_url(), {"text": "Hi"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CragComment.objects.count(), 0)

    def test_user_can_comment_and_it_is_shown_with_author(self):
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(self.add_url(), {"text": "Path is washed out"})
        response = self.client.get(reverse("crags:detail", args=[self.published.pk]))
        self.assertContains(response, "Path is washed out")
        self.assertContains(response, "bob")

    def test_author_can_comment_on_own_crag(self):
        self.client.login(username="alice", password="pw-alice-123")
        self.client.post(self.add_url(), {"text": "Thanks!"})
        self.assertEqual(CragComment.objects.count(), 1)

    def test_cannot_comment_on_unpublished_crag(self):
        self.client.login(username="bob", password="pw-bob-123")
        response = self.client.post(self.add_url(self.pending), {"text": "Hi"})
        self.assertEqual(response.status_code, 404)

    def test_empty_and_too_long_comments_are_rejected(self):
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(self.add_url(), {"text": "   "})
        self.client.post(self.add_url(), {"text": "x" * (CragComment.MAX_LENGTH + 1)})
        self.assertEqual(CragComment.objects.count(), 0)

    def test_owner_and_staff_can_delete_others_cannot(self):
        comment = CragComment.objects.create(crag=self.published, user=self.bob, text="Hi")
        url = reverse("crags:comment_delete", args=[comment.pk])
        self.client.login(username="alice", password="pw-alice-123")
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(CragComment.objects.count(), 1)
        self.client.login(username="bob", password="pw-bob-123")
        self.client.post(url)
        self.assertEqual(CragComment.objects.count(), 0)
        comment = CragComment.objects.create(crag=self.published, user=self.bob, text="Hi")
        self.client.login(username="staff", password="pw-staff-123")
        self.client.post(reverse("crags:comment_delete", args=[comment.pk]))
        self.assertEqual(CragComment.objects.count(), 0)

    def test_list_shows_comment_count(self):
        CragComment.objects.create(crag=self.published, user=self.bob, text="One")
        CragComment.objects.create(crag=self.published, user=self.staff, text="Two")
        response = self.client.get(reverse("crags:list"))
        self.assertContains(response, "💬 2")


class StaffReviewTests(CragTestBase):
    def test_submit_sets_pending_and_submitted_at(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("crags:edit", args=[self.draft.pk]),
            form_data(self.area, name="Draft entry", action="submit"),
        )
        self.assertEqual(response.status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Crag.Status.PENDING)
        self.assertIsNotNone(self.draft.submitted_at)
        response = self.client.get(reverse("crags:detail", args=[self.draft.pk]))
        self.assertContains(response, "Pending review")

    def test_publish_sets_audit_fields(self):
        self.pending.transition(Crag.Status.PUBLISHED, self.staff)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Crag.Status.PUBLISHED)
        self.assertEqual(self.pending.reviewed_by, self.staff)
        self.assertIsNotNone(self.pending.reviewed_at)

    def test_return_requires_reason(self):
        with self.assertRaises(ValidationError):
            self.pending.transition(Crag.Status.NEEDS_CHANGES, self.staff, "short")
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Crag.Status.PENDING)

    def test_invalid_transition_changes_nothing(self):
        with self.assertRaises(InvalidTransition):
            self.published.transition(Crag.Status.DRAFT, self.staff)
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Crag.Status.PUBLISHED)

    def test_returned_crag_visibility_and_resubmit(self):
        self.pending.transition(
            Crag.Status.NEEDS_CHANGES, self.staff, "Please add a parking location."
        )
        url = reverse("crags:detail", args=[self.pending.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(url), "Please add a parking location.")
        self.assertContains(
            self.client.get(reverse("crags:mine")), "Please add a parking location."
        )
        self.client.post(
            reverse("crags:edit", args=[self.pending.pk]),
            form_data(self.area, name="Waiting", action="submit"),
        )
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Crag.Status.PENDING)
        self.assertEqual(self.pending.review_reason, "")

    def _admin_post(self, user, action, crags, **extra):
        self.client.force_login(user)
        data = {
            "action": action,
            "_selected_action": [c.pk for c in crags],
            **extra,
        }
        return self.client.post(reverse("admin:crags_crag_changelist"), data)

    def test_admin_return_action_needs_reason(self):
        admin_user = User.objects.create_superuser("root", "r@example.com", "pw-root-123")
        response = self._admin_post(admin_user, "return_to_submitter", [self.pending], apply="1", reason="no")
        self.assertEqual(response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Crag.Status.PENDING)
        self._admin_post(
            admin_user, "return_to_submitter", [self.pending],
            apply="1", reason="Please add photos of the base.",
        )
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Crag.Status.NEEDS_CHANGES)

    def test_staff_without_permission_gets_no_actions(self):
        self.staff.user_permissions.add(
            *__import__("django.contrib.auth.models", fromlist=["Permission"])
            .Permission.objects.filter(codename__in=["view_crag", "change_crag"])
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:crags_crag_changelist"))
        self.assertNotContains(response, "Publish selected crags")


class ReviewEmailTests(CragTestBase):
    def test_publish_sends_mail_with_link(self):
        self.pending.transition(Crag.Status.PUBLISHED, self.staff)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["alice@example.com"])
        self.assertIn("Waiting", message.body)
        self.assertIn(reverse("crags:detail", args=[self.pending.pk]), message.body)

    def test_return_mail_contains_reason(self):
        self.pending.transition(Crag.Status.NEEDS_CHANGES, self.staff, "Add a parking location.")
        self.assertIn("Add a parking location.", mail.outbox[0].body)

    def test_submit_and_reject_send_no_mail(self):
        self.draft.transition(Crag.Status.PENDING, self.alice)
        self.pending.transition(Crag.Status.REJECTED, self.staff)
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_failure_does_not_block_transition(self):
        with self.settings(EMAIL_BACKEND="crags.tests.BrokenBackend"):
            with self.assertLogs("crags.notifications", level="ERROR"):
                self.pending.transition(Crag.Status.PUBLISHED, self.staff)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Crag.Status.PUBLISHED)


from django.core.mail.backends.base import BaseEmailBackend


class BrokenBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise RuntimeError("provider down")


class ResubmitPublishedTests(CragTestBase):
    def _submit(self, user):
        self.client.force_login(user)
        response = self.client.post(
            reverse("crags:edit", args=[self.published.pk]),
            form_data(self.area, name="Public", action="submit"),
        )
        self.published.refresh_from_db()
        return response

    def test_owner_submit_on_published_goes_pending(self):
        self.assertEqual(self._submit(self.alice).status_code, 302)
        self.assertEqual(self.published.status, Crag.Status.PENDING)
        self.assertIsNotNone(self.published.submitted_at)

    def test_staff_submit_on_published_goes_pending(self):
        self.assertEqual(self._submit(self.staff).status_code, 302)
        self.assertEqual(self.published.status, Crag.Status.PENDING)


class ReturnPublishedTests(CragTestBase):
    def test_published_crag_can_be_returned_with_reason(self):
        self.published.transition(
            Crag.Status.NEEDS_CHANGES, self.staff, "Parking info is outdated."
        )
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Crag.Status.NEEDS_CHANGES)
        self.assertEqual(self.published.review_reason, "Parking info is outdated.")
        self.assertIn("Parking info is outdated.", mail.outbox[0].body)
        url = reverse("crags:detail", args=[self.published.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Parking info is outdated.", status_code=404)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(url), "Parking info is outdated.")

    def test_published_return_still_needs_reason(self):
        with self.assertRaises(ValidationError):
            self.published.transition(Crag.Status.NEEDS_CHANGES, self.staff, "")


class ReviewQueueAdminTests(CragTestBase):
    def setUp(self):
        self.root = User.objects.create_superuser("root", "r@example.com", "pw-root-123")
        self.client.force_login(self.root)

    def test_queue_lists_pending_oldest_first_with_photo_count(self):
        from datetime import timedelta
        from django.utils import timezone

        now = timezone.now()
        newer = Crag.objects.create(
            name="Newer", area=self.area, created_by=self.alice,
            status=Crag.Status.PENDING, submitted_at=now,
        )
        Crag.objects.filter(pk=self.pending.pk).update(submitted_at=now - timedelta(days=3))
        Photo.objects.create(crag=newer, image="crags/x.webp")
        Photo.objects.create(crag=newer, image="crags/y.webp")

        response = self.client.get(reverse("admin:crags_crag_changelist"), {"queue": "pending"})

        self.assertEqual(response.status_code, 200)
        rows = list(response.context["cl"].result_list)
        self.assertEqual([c.name for c in rows], ["Waiting", "Newer"])
        self.assertEqual([c._photo_count for c in rows], [0, 2])
        self.assertNotContains(response, "Draft entry")
