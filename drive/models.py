import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def user_upload_path(instance, filename):
    suffix = Path(filename).suffix[:20]
    return f"users/{instance.owner_id}/{uuid.uuid4().hex}{suffix}"


class Folder(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="folders")
    parent = models.ForeignKey(
        "self",
        on_delete=models.RESTRICT,
        related_name="children",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        indexes = [models.Index(fields=["owner", "parent", "name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "parent", "name"],
                condition=models.Q(parent__isnull=False),
                name="unique_folder_name_in_parent",
            ),
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=models.Q(parent__isnull=True),
                name="unique_root_folder_name",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        if not self.name or self.name in {".", ".."} or any(character in self.name for character in ("/", "\\", "\x00")):
            raise ValidationError({"name": "Введите корректное имя папки."})
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({"parent": "Папка не может быть родителем самой себя."})
            if self.owner_id and self.parent.owner_id != self.owner_id:
                raise ValidationError({"parent": "Родительская папка должна принадлежать тому же владельцу."})
            seen = set()
            ancestor_id = self.parent_id
            while ancestor_id:
                if ancestor_id == self.pk or ancestor_id in seen:
                    raise ValidationError({"parent": "Папки не могут образовывать цикл."})
                seen.add(ancestor_id)
                ancestor_id = self.__class__.objects.filter(pk=ancestor_id).values_list("parent_id", flat=True).first()

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    def breadcrumbs(self):
        chain = []
        current = self
        seen = set()
        while current:
            if current.pk in seen or current.owner_id != self.owner_id:
                raise ValidationError("Повреждённое дерево папок.")
            seen.add(current.pk)
            chain.append(current)
            current = current.parent
        return list(reversed(chain))


class StoredFile(models.Model):
    PREVIEWABLE_CONTENT_TYPES = {
        "image/avif",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    class StorageBackend(models.TextChoices):
        LOCAL = "local", "Локальное хранилище"
        S3 = "s3", "S3-совместимое хранилище"
        GATEWAY = "gateway", "Go storage gateway"

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Ожидает проверки"
        CLEAN = "clean", "Проверен"
        INFECTED = "infected", "В карантине"
        ERROR = "error", "Сканер недоступен"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stored_files")
    folder = models.ForeignKey(
        Folder,
        on_delete=models.RESTRICT,
        related_name="stored_files",
        null=True,
        blank=True,
    )
    display_name = models.CharField(max_length=255)
    blob = models.FileField(upload_to=user_upload_path, max_length=500)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=255, blank=True)
    favorite = models.BooleanField(default=False)
    scan_status = models.CharField(max_length=20, choices=ScanStatus.choices, default=ScanStatus.PENDING, db_index=True)
    scan_report = models.CharField(max_length=255, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    storage_backend = models.CharField(max_length=20, choices=StorageBackend.choices, default=StorageBackend.LOCAL, db_index=True)
    object_key = models.CharField(max_length=500, blank=True)
    provider_version = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.display_name

    @property
    def downloadable(self):
        from django.conf import settings
        return self.scan_status == self.ScanStatus.CLEAN or (self.scan_status == self.ScanStatus.ERROR and not settings.MALWARE_SCAN_REQUIRED)

    @property
    def previewable(self):
        return self.downloadable and self.content_type.casefold() in self.PREVIEWABLE_CONTENT_TYPES

    @property
    def storage_key(self):
        return self.object_key or self.blob.name


class UploadSession(models.Model):
    class State(models.TextChoices):
        UPLOADING = "uploading", "Загрузка"
        ASSEMBLING = "assembling", "Сборка"
        COMPLETE = "complete", "Завершена"
        ABORTED = "aborted", "Отменена"
        FAILED = "failed", "Ошибка"

    class Backend(models.TextChoices):
        LOCAL = "local", "Локальные части"
        GATEWAY = "gateway", "Go storage gateway"
        S3 = "s3", "S3 multipart"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions")
    folder = models.ForeignKey(Folder, on_delete=models.RESTRICT, related_name="upload_sessions", null=True, blank=True)
    display_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True)
    total_size = models.PositiveBigIntegerField()
    chunk_size = models.PositiveIntegerField()
    received_parts = models.JSONField(default=list)
    backend = models.CharField(max_length=20, choices=Backend.choices, default=Backend.LOCAL)
    backend_upload_id = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.UPLOADING, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "state", "expires_at"])]
        constraints = [models.UniqueConstraint(fields=["owner", "idempotency_key"], condition=~models.Q(idempotency_key=""), name="unique_upload_idempotency_key")]
