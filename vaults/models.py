import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Vault(models.Model):
    """An immutable vault identity; revocation keeps its UUID unavailable forever."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cipher_vaults")
    version = models.PositiveSmallIntegerField(default=1)
    wrapped_key = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner"], condition=models.Q(revoked_at__isnull=True), name="one_active_cipher_vault"),
            models.CheckConstraint(condition=models.Q(version=1), name="cipher_vault_version_one"),
        ]


class CipherFolder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vault = models.ForeignKey(Vault, on_delete=models.CASCADE, related_name="folders")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    metadata = models.JSONField()
    starred = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class CipherFile(models.Model):
    """Only ciphertext and opaque identifiers: no plaintext name, type, or key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vault = models.ForeignKey(Vault, on_delete=models.CASCADE, related_name="files")
    metadata = models.JSONField()
    parent = models.ForeignKey(CipherFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name="files")
    starred = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(null=True, blank=True)
    ciphertext_bytes = models.PositiveBigIntegerField()
    storage_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(ciphertext_bytes__gte=16), name="cipher_file_has_tag")]


class BlobDeletion(models.Model):
    """Durable cleanup for revoked objects and abandoned upload staging blobs."""

    storage_key = models.CharField(max_length=255, unique=True)
    not_before = models.DateTimeField(default=timezone.now, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
