from django.db import migrations
from django.utils import timezone


def reasons_to_messages(apps, schema_editor):
    """Crags sent back before the review thread existed: keep their reason in it."""
    Crag = apps.get_model("crags", "Crag")
    ReviewMessage = apps.get_model("crags", "ReviewMessage")
    for crag in Crag.objects.filter(status="NEEDS_CHANGES").exclude(review_reason=""):
        if not ReviewMessage.objects.filter(crag=crag).exists():
            ReviewMessage.objects.create(
                crag=crag,
                author_id=crag.reviewed_by_id,
                kind="RETURNED",
                text=crag.review_reason,
                created_at=crag.reviewed_at or timezone.now(),
            )


class Migration(migrations.Migration):
    dependencies = [("crags", "0023_review_message")]

    operations = [migrations.RunPython(reasons_to_messages, migrations.RunPython.noop)]
