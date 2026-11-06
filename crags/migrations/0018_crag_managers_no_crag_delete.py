from django.db import migrations


def remove_delete_crag(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    db = schema_editor.connection.alias
    for group in Group.objects.using(db).filter(name="Crag Managers"):
        group.permissions.remove(
            *Permission.objects.using(db).filter(
                content_type__app_label="crags", codename="delete_crag"
            )
        )


def restore_delete_crag(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    db = schema_editor.connection.alias
    for group in Group.objects.using(db).filter(name="Crag Managers"):
        group.permissions.add(
            *Permission.objects.using(db).filter(
                content_type__app_label="crags", codename="delete_crag"
            )
        )


class Migration(migrations.Migration):
    dependencies = [("crags", "0017_staff_review")]

    operations = [migrations.RunPython(remove_delete_crag, restore_delete_crag)]
