from django.db import migrations


def seed_features(apps, schema_editor):
    Feature = apps.get_model("crags", "Feature")
    Feature.objects.bulk_create(
        [
            Feature(slug="rockfall", label="Rockfall"),
            Feature(slug="fall_hazard", label="Fall hazard"),
            Feature(slug="stroller_friendly", label="Stroller-friendly"),
        ]
    )


def remove_seeded_features(apps, schema_editor):
    Feature = apps.get_model("crags", "Feature")
    Feature.objects.filter(
        slug__in=["rockfall", "fall_hazard", "stroller_friendly"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("crags", "0005_feature_crag_approach_assessed_crag_base_assessed_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_features, remove_seeded_features),
    ]
