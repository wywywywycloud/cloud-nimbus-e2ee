import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


def new_user_handle():
    return secrets.token_bytes(32)


class PasskeyIdentity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkey_identity")
    user_handle = models.BinaryField(default=new_user_handle, unique=True, editable=False)


class PasskeyCredential(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkey_credentials")
    credential_id = models.CharField(max_length=1400, unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    backup_eligible = models.BooleanField(default=False)
    backed_up = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    vault = models.ForeignKey("vaults.Vault", on_delete=models.CASCADE, null=True, related_name="passkey_credentials")
    wrapped_key = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user"], condition=Q(active=True), name="one_active_passkey_per_user")]


class PasskeyChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True)
    session_digest = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PasskeyReset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True)
    session_digest = models.CharField(max_length=64)
    telegram_user_id = models.PositiveBigIntegerField(null=True)
    code_digest = models.CharField(max_length=64)
    auth_hash = models.CharField(max_length=64, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
