import hashlib

from django.conf import settings
from django.db import models


class SecurityEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="security_events")
    event = models.CharField(max_length=80, db_index=True)
    success = models.BooleanField(default=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def hash_ip(ip):
        if not ip:
            return ""
        return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()


class RateBucket(models.Model):
    action = models.CharField(max_length=50)
    key_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["action", "key_hash", "window_start"], name="unique_rate_bucket")]
