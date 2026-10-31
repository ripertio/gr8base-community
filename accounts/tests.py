import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from crags.models import Area, Crag

from .models import User


def image_upload(name="a.png", size=(800, 600)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pw-alice-123")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "pw-bob-123")
        cls.staff = User.objects.create_user(
            "staff", "staff@example.com", "pw-staff-123", is_staff=True
        )
        area = Area.objects.create(name="Test area")
        cls.public_crag = Crag.objects.create(
            name="Public crag", area=area, created_by=cls.alice, status=Crag.Status.PUBLISHED
        )
        cls.draft_crag = Crag.objects.create(
            name="Draft crag", area=area, created_by=cls.alice, status=Crag.Status.DRAFT
        )
        cls.url = reverse("profiles:detail", args=["alice"])

    def test_private_profile_hidden_from_others(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_private_profile_visible_to_owner_and_staff(self):
        for user in (self.alice, self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_crag_detail_links_author_only_if_profile_public(self):
        detail = reverse("crags:detail", args=[self.public_crag.pk])
        self.assertNotContains(self.client.get(detail), self.url)
        self.alice.profile_public = True
        self.alice.save()
        self.assertContains(self.client.get(detail), f'href="{self.url}"')

    def test_public_profile_lists_only_public_crags(self):
        self.alice.profile_public = True
        self.alice.save()
        response = self.client.get(self.url)
        self.assertContains(response, "Public crag")
        self.assertNotContains(response, "Draft crag")

    def test_edit_requires_login(self):
        response = self.client.get(reverse("profiles:edit"))
        self.assertRedirects(
            response, "/accounts/login/?next=/profile/edit/", fetch_redirect_response=False
        )

    def test_edit_updates_own_profile(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("profiles:edit"), {"bio": "I climb.", "profile_public": "on"}
        )
        self.assertRedirects(response, self.url)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.bio, "I climb.")
        self.assertTrue(self.alice.profile_public)

    def test_avatar_upload_is_processed_and_replaced(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.client.force_login(self.alice)
            self.client.post(reverse("profiles:edit"), {"avatar": image_upload(size=(1000, 800))})
            self.alice.refresh_from_db()
            first = self.alice.avatar.name
            self.assertTrue(first.startswith("avatars/") and first.endswith(".webp"))
            self.assertLessEqual(max(Image.open(self.alice.avatar).size), 400)

            self.client.post(reverse("profiles:edit"), {"avatar": image_upload()})
            self.alice.refresh_from_db()
            self.assertNotEqual(first, self.alice.avatar.name)
            self.assertFalse(self.alice.avatar.storage.exists(first))

    def test_remove_avatar(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.client.force_login(self.alice)
            self.client.post(reverse("profiles:edit"), {"avatar": image_upload()})
            self.alice.refresh_from_db()
            name = self.alice.avatar.name
            self.client.post(reverse("profiles:edit"), {"remove_avatar": "on"})
            self.alice.refresh_from_db()
            self.assertFalse(self.alice.avatar)
            self.assertFalse(self.alice.avatar.storage.exists(name))

    def test_invalid_avatar_rejected(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.client.force_login(self.alice)
            bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
            response = self.client.post(reverse("profiles:edit"), {"avatar": bad})
            self.assertEqual(response.status_code, 200)
            self.alice.refresh_from_db()
            self.assertFalse(self.alice.avatar)
