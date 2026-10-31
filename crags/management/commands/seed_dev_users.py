from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crags.models import Crag, Photo

DEV_ROOT_USERNAME = "dev-root"
DEV_ROOT_PASSWORD = "dev-root"
DEV_ROOT_EMAIL = "dev-root@localhost"


class Command(BaseCommand):
    help = "Create the dev-root superuser and give it all ownerless crags and photos (DEBUG only)."

    @transaction.atomic
    def handle(self, *args, **options):
        # A known password must never end up on production
        if not settings.DEBUG:
            raise CommandError("Refusing to run with DEBUG=False.")

        User = get_user_model()
        root, created = User.objects.get_or_create(
            username=DEV_ROOT_USERNAME,
            defaults={"email": DEV_ROOT_EMAIL},
        )
        root.email = DEV_ROOT_EMAIL
        root.is_staff = True
        root.is_superuser = True
        root.set_password(DEV_ROOT_PASSWORD)
        root.save()

        # allauth: verified primary address, so email login works without a confirmation mail
        EmailAddress.objects.update_or_create(
            user=root,
            email=DEV_ROOT_EMAIL,
            defaults={"verified": True, "primary": True},
        )

        crags = Crag.objects.filter(created_by__isnull=True).update(created_by=root)
        photos = Photo.objects.filter(uploaded_by__isnull=True).update(uploaded_by=root)

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} {DEV_ROOT_USERNAME} (password: {DEV_ROOT_PASSWORD}), "
            f"assigned {crags} crags and {photos} photos."
        ))
