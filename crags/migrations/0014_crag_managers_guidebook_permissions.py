from django.db import migrations

GROUP_NAME = "Crag Managers"
PERMISSIONS = ("add", "view", "change", "delete")


def grant_guidebook_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    database = schema_editor.connection.alias
    group, _ = Group.objects.using(database).get_or_create(name=GROUP_NAME)
    content_type, _ = ContentType.objects.using(database).get_or_create(
        app_label="crags",
        model="guidebook",
    )
    for action in PERMISSIONS:
        permission, _ = Permission.objects.using(database).get_or_create(
            content_type=content_type,
            codename=f"{action}_guidebook",
            defaults={"name": f"Can {action} guidebook"},
        )
        group.permissions.add(permission)


def revoke_guidebook_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    database = schema_editor.connection.alias
    group = Group.objects.using(database).filter(name=GROUP_NAME).first()
    if group is not None:
        group.permissions.remove(
            *Permission.objects.using(database).filter(
                content_type__app_label="crags",
                content_type__model="guidebook",
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("crags", "0013_remove_crag_guidebook"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(grant_guidebook_permissions, revoke_guidebook_permissions),
    ]
