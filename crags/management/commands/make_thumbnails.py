from django.core.management.base import BaseCommand

from crags.models import Photo


class Command(BaseCommand):
    help = "Create thumbnails for photos that don't have one yet (--all: recreate every thumbnail)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true", help="Recreate existing thumbnails too."
        )

    def handle(self, *args, **options):
        photos = Photo.objects.order_by("pk")
        if not options["all"]:
            photos = photos.filter(thumbnail="")

        done = failed = 0
        for photo in photos.iterator():
            if photo.make_thumbnail():
                done += 1
            else:
                failed += 1
                self.stderr.write(f"Photo {photo.pk}: could not read {photo.image.name}")

        self.stdout.write(self.style.SUCCESS(f"Created {done} thumbnail(s), {failed} failed."))
