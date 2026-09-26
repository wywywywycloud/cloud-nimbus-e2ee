import uuid

from django.conf import settings
from django.db import models


class TotpCredential(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_credential")
    # This shared authentication secret is server-visible. It is never a vault key.
    secret = models.CharField(max_length=64)
    last_counter = models.BigIntegerField(default=-1)
    created_at = models.DateTimeField(auto_now_add=True)


class OtpChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    method = models.CharField(max_length=16)
    session_digest = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
