import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .i18n import SUPPORTED_LANGUAGES

DEFAULT_QUOTA_BYTES = 50 * 1024 * 1024


class User(AbstractUser):
    class AuthMode(models.TextChoices):
        CODE = "code", "Только код"
        PASSWORD = "password", "Только пароль"
        CODE_PASSWORD = "code_password", "Код и пароль"

    class UITheme(models.TextChoices):
        DARK = "dark", _("Тёмная")
        LIGHT = "light", _("Светлая")

    class ViewMode(models.TextChoices):
        GRID = "grid", "Сетка"
        LIST = "list", "Список"

    class DisplayDensity(models.TextChoices):
        COMFORTABLE = "comfortable", "Комфортная"
        COMPACT = "compact", "Компактная"

    class FileSort(models.TextChoices):
        NAME = "name", "По названию"
        MODIFIED = "modified", "Сначала недавно изменённые"
        SIZE = "size", "Сначала крупные"

    email = models.EmailField("почта", blank=True, default="")
    email_verified = models.BooleanField(default=False)
    auth_mode = models.CharField(max_length=20, choices=AuthMode.choices, default=AuthMode.CODE)
    ui_theme = models.CharField(max_length=5, choices=UITheme.choices, default=UITheme.DARK)
    language = models.CharField(max_length=5, choices=SUPPORTED_LANGUAGES, default="ru")
    default_view_mode = models.CharField(max_length=4, choices=ViewMode.choices, default=ViewMode.GRID)
    display_density = models.CharField(max_length=12, choices=DisplayDensity.choices, default=DisplayDensity.COMFORTABLE)
    default_file_sort = models.CharField(max_length=10, choices=FileSort.choices, default=FileSort.NAME)
    folders_first = models.BooleanField(default=True)
    show_image_previews = models.BooleanField(default=True)
    email_share_notifications = models.BooleanField(default=True)
    used_bytes = models.PositiveBigIntegerField(default=0)
    reserved_bytes = models.PositiveBigIntegerField(default=0)
    quota_bytes = models.PositiveBigIntegerField(default=DEFAULT_QUOTA_BYTES)
    telegram_user_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    telegram_first_name = models.CharField(max_length=128, blank=True)
    telegram_linked_at = models.DateTimeField(null=True, blank=True)
    passkey_risk_accepted_at = models.DateTimeField(null=True, blank=True)
    scheduled_deletion_at = models.DateTimeField(null=True, blank=True, db_index=True)

    def save(self, *args, **kwargs):
        self.email = self.__class__.objects.normalize_email(self.email).lower()
        super().save(*args, **kwargs)

    @property
    def telegram_display_name(self):
        if self.telegram_username:
            return f"@{self.telegram_username}"
        return self.telegram_first_name or (str(self.telegram_user_id) if self.telegram_user_id else "")


class TelegramLinkAttempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_link_attempts")
    token_digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    telegram_sender_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-created_at"])]

    @staticmethod
    def digest_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()


class OneTimeCode(models.Model):
    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "verify_email", "Подтверждение почты"
        LOGIN = "login", "Вход"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="one_time_codes")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "-created_at"])]

    @staticmethod
    def digest_code(code: str) -> str:
        return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()

    @classmethod
    def issue(cls, user, purpose, code):
        cls.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(consumed_at=timezone.now())
        return cls.objects.create(
            user=user,
            purpose=purpose,
            digest=cls.digest_code(code),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def verify(self, code: str) -> bool:
        from django.db import transaction
        with transaction.atomic():
            locked = self.__class__.objects.select_for_update().get(pk=self.pk)
            if locked.consumed_at or locked.expires_at <= timezone.now() or locked.attempts >= 5:
                return False
            locked.attempts += 1
            valid = hmac.compare_digest(locked.digest, self.digest_code(code.strip()))
            if valid:
                locked.consumed_at = timezone.now()
            locked.save(update_fields=["attempts", "consumed_at"])
            self.attempts = locked.attempts
            self.consumed_at = locked.consumed_at
            return valid
