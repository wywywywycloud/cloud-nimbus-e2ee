from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_language_user_ui_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="telegram_first_name",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="user",
            name="telegram_linked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="telegram_user_id",
            field=models.PositiveBigIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="user",
            name="telegram_username",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.CreateModel(
            name="TelegramLinkAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("telegram_chat_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("telegram_sender_id", models.PositiveBigIntegerField(blank=True, db_index=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_link_attempts", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "-created_at"], name="accounts_te_user_id_dcc69f_idx")],
            },
        ),
    ]
