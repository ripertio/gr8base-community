from django.db import migrations


def text_to_guidebooks(apps, schema_editor):
    Crag = apps.get_model("crags", "Crag")
    Guidebook = apps.get_model("crags", "Guidebook")

    cache = {}
    for crag in Crag.objects.exclude(guidebook=""):
        name = crag.guidebook.strip()
        if not name:
            continue
        guidebook = cache.get(name)
        if guidebook is None:
            guidebook, _ = Guidebook.objects.get_or_create(name=name)
            cache[name] = guidebook
        crag.guidebooks.add(guidebook)


def guidebooks_to_text(apps, schema_editor):
    # Lossy by nature: the old field holds a single string, so only the
    # first guidebook of each crag is written back.
    Crag = apps.get_model("crags", "Crag")
    for crag in Crag.objects.filter(guidebooks__isnull=False).distinct():
        first = crag.guidebooks.order_by("name").first()
        crag.guidebook = first.name[:250]
        crag.save(update_fields=["guidebook"])


class Migration(migrations.Migration):

    dependencies = [
        ("crags", "0011_guidebook"),
    ]

    operations = [
        migrations.RunPython(text_to_guidebooks, guidebooks_to_text),
    ]
