from django.db import migrations


FIFTY_MIB = 50 * 1024 * 1024


def make_storage_available(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(quota_bytes=0).update(quota_bytes=FIFTY_MIB)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_telegram_linking")]

    operations = [migrations.RunPython(make_storage_available, migrations.RunPython.noop)]
