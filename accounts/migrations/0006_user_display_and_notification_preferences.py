from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_make_storage_available_before_telegram")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="default_view_mode",
            field=models.CharField(choices=[("grid", "Сетка"), ("list", "Список")], default="grid", max_length=4),
        ),
        migrations.AddField(
            model_name="user",
            name="display_density",
            field=models.CharField(choices=[("comfortable", "Комфортная"), ("compact", "Компактная")], default="comfortable", max_length=12),
        ),
        migrations.AddField(
            model_name="user",
            name="default_file_sort",
            field=models.CharField(choices=[("name", "По названию"), ("modified", "Сначала недавно изменённые"), ("size", "Сначала крупные")], default="name", max_length=10),
        ),
        migrations.AddField(model_name="user", name="folders_first", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="user", name="show_image_previews", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="user", name="email_share_notifications", field=models.BooleanField(default=True)),
    ]
