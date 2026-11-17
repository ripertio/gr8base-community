import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


def avatar_upload_path(instance, filename):
    return f"avatars/{uuid.uuid4().hex}.webp"


class User(AbstractUser):
    bio = models.TextField(blank=True, max_length=500)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True)
    profile_public = models.BooleanField(
        default=False,
        help_text="Allow anyone to see your profile and your public crags.",
    )
    # Channels per notification type, e.g. {"COMMENT": {"in_app": true, "email": false}}.
    # Only what the user changed is stored; crags/notifications.py has the defaults.
    notification_settings = models.JSONField(default=dict, blank=True)
