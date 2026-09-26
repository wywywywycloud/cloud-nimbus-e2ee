import base64
import hashlib
import hmac
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from drive.models import Folder, StoredFile


class ShareLink(models.Model):
    class AccessMode(models.TextChoices):
        ANYONE = "anyone", "Любой по ссылке"
        SIGNED_IN = "signed_in", "Только после входа"
        PASSWORD = "password", "Вход и пароль ссылки"
        RESTRICTED = "restricted", "Только приглашённые"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="share_links")
    file = models.ForeignKey(StoredFile, on_delete=models.CASCADE, related_name="share_links", null=True, blank=True)
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="share_links", null=True, blank=True)
    access_mode = models.CharField(max_length=20, choices=AccessMode.choices, default=AccessMode.ANYONE)
    password_hash = models.CharField(max_length=128, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    revision = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "file", "active"]),
            models.Index(fields=["owner", "folder", "active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(file__isnull=False, folder__isnull=True) | models.Q(file__isnull=True, folder__isnull=False)),
                name="sharing_link_exactly_one_target",
            ),
        ]

    def __str__(self):
        return f"{self.target_name} ({self.get_access_mode_display()})"

    @property
    def target(self):
        return self.folder or self.file

    @property
    def target_name(self):
        return self.folder.name if self.folder_id else self.file.display_name

    def clean(self):
        super().clean()
        if bool(self.file_id) == bool(self.folder_id):
            raise ValidationError("Ссылка должна вести ровно на один файл или папку.")
        target = self.target
        if target and self.owner_id and target.owner_id != self.owner_id:
            raise ValidationError("Владелец ссылки должен владеть объектом.")
        if self.access_mode == self.AccessMode.PASSWORD and not self.password_hash:
            raise ValidationError({"password_hash": "Для этого режима нужен пароль ссылки."})

    @property
    def is_available(self):
        return self.active and (self.expires_at is None or self.expires_at > timezone.now())

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return bool(self.password_hash) and check_password(raw_password, self.password_hash)

    @property
    def public_token(self):
        signature = hmac.new(settings.SECRET_KEY.encode(), b"cloud-nimbus-share:" + self.pk.bytes, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(self.pk.bytes + signature).decode().rstrip("=")

    @classmethod
    def resolve_token(cls, token):
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            if len(raw) != 48:
                return None
            canonical = base64.urlsafe_b64encode(raw).decode().rstrip("=")
            if not hmac.compare_digest(token, canonical):
                return None
            share_id = uuid.UUID(bytes=raw[:16])
            expected = hmac.new(settings.SECRET_KEY.encode(), b"cloud-nimbus-share:" + raw[:16], hashlib.sha256).digest()
            if not hmac.compare_digest(raw[16:], expected):
                return None
            return cls.objects.select_related("file", "folder", "owner").filter(pk=share_id).first()
        except (ValueError, TypeError):
            return None


class FileGrant(models.Model):
    class Role(models.TextChoices):
        VIEWER = "viewer", "Просмотр"
        EDITOR = "editor", "Редактирование"

    file = models.ForeignKey(StoredFile, on_delete=models.CASCADE, related_name="grants", null=True, blank=True)
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="grants", null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="issued_file_grants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="file_grants",
        null=True,
        blank=True,
    )
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email", "user_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user__isnull=False) | ~models.Q(email=""),
                name="sharing_grant_has_recipient",
            ),
            models.UniqueConstraint(fields=["file", "user"], name="sharing_unique_file_user_grant"),
            models.UniqueConstraint(fields=["file", "email"], name="sharing_unique_file_email_grant"),
            models.UniqueConstraint(fields=["folder", "user"], name="sharing_unique_folder_user_grant"),
            models.UniqueConstraint(fields=["folder", "email"], name="sharing_unique_folder_email_grant"),
            models.CheckConstraint(
                condition=(models.Q(file__isnull=False, folder__isnull=True) | models.Q(file__isnull=True, folder__isnull=False)),
                name="sharing_grant_exactly_one_target",
            ),
        ]
        indexes = [models.Index(fields=["file", "role"]), models.Index(fields=["folder", "role"])]

    @property
    def target(self):
        return self.folder or self.file

    def clean(self):
        super().clean()
        if bool(self.file_id) == bool(self.folder_id):
            raise ValidationError("Доступ должен относиться ровно к одному файлу или папке.")
        target = self.target
        if target and self.granted_by_id and target.owner_id != self.granted_by_id:
            raise ValidationError("Выдавать доступ может только владелец объекта.")
        if not self.user_id and not self.email:
            raise ValidationError("Укажите пользователя или почту.")

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        elif self.user_id:
            self.email = self.user.email.lower()
        super().save(*args, **kwargs)
