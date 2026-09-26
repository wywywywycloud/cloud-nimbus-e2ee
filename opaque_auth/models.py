import uuid

from django.conf import settings
from django.db import models


class OpaqueCredential(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opaque_credential")
    registration_record = models.TextField()
    version = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class OpaqueChallenge(models.Model):
    class Kind(models.TextChoices):
        REGISTER = "register", "Registration"
        LOGIN = "login", "Login"
        CHANGE = "change", "Password change"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    session_digest = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
