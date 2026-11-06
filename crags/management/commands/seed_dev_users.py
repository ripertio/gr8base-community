from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crags.models import Crag, Photo

DEV_ROOT_USERNAME = "dev-root"
DEV_ROOT_PASSWORD = "dev-root"
DEV_ROOT_EMAIL = "dev-root@localhost"

# Regular dev users for trying out features as non-staff (password = username).
# "author" owns the crag below, so dummy1/dummy2 can rate it as non-authors.
DEV_USERNAMES = ("author", "dummy1", "dummy2")
DEV_AUTHOR_CRAG = "Grauer Stein"


def make_dev_user(username):
    User = get_user_model()
    email = f"{username}@localhost"
    user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
    user.email = email
    user.set_password(username)
    user.save()
    EmailAddress.objects.update_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    return user


class Command(BaseCommand):
    help = (
        "Create dev-root (superuser) plus author/dummy1/dummy2, give dev-root all "
        "ownerless crags and photos and hand 'Grauer Stein' to author (DEBUG only)."
    )

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

        users = {name: make_dev_user(name) for name in DEV_USERNAMES}
        owned = Crag.objects.filter(name=DEV_AUTHOR_CRAG).update(created_by=users["author"])
        if not owned:
            self.stdout.write(self.style.WARNING(f"Crag '{DEV_AUTHOR_CRAG}' not found."))

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} {DEV_ROOT_USERNAME} (password: {DEV_ROOT_PASSWORD}), "
            f"assigned {crags} crags and {photos} photos. "
            f"Users {', '.join(DEV_USERNAMES)} (password = username); "
            f"'{DEV_AUTHOR_CRAG}' now belongs to author."
        ))
