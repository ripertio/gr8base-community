from django.db import migrations


GROUP_NAME = "Crag Managers"
MANAGED_MODELS = {"area": "area", "crag": "crag"}
PERMISSIONS = ("add", "view", "change", "delete")


def create_crag_managers_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    database = schema_editor.connection.alias
    group, _ = Group.objects.using(database).get_or_create(name=GROUP_NAME)

    for model, singular in MANAGED_MODELS.items():
        content_type, _ = ContentType.objects.using(database).get_or_create(
            app_label="crags",
            model=model,
        )
        for action in PERMISSIONS:
            codename = f"{action}_{model}"
            permission, _ = Permission.objects.using(database).get_or_create(
                content_type=content_type,
                codename=codename,
                defaults={"name": f"Can {action} {singular}"},
            )
            group.permissions.add(permission)


def remove_crag_managers_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.using(schema_editor.connection.alias).filter(
        name=GROUP_NAME
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("crags", "0009_alter_photo_category"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(
            create_crag_managers_group,
            remove_crag_managers_group,
        ),
    ]
