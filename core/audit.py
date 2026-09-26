import hashlib
import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import RateBucket, SecurityEvent

logger = logging.getLogger("cloud_nimbus.security")


def client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def audit(request, event, *, success=True, actor=None, **metadata):
    allowed = {"mode", "count", "bytes", "file_id", "folder_id", "parent_id", "grant_id", "status", "reason", "share_id", "language", "ui_theme"}
    actor = actor if actor is not None else (request.user if getattr(request, "user", None) and request.user.is_authenticated else None)
    safe_metadata = {key: value for key, value in metadata.items() if key in allowed and isinstance(value, (str, int, float, bool, type(None)))}
    try:
        SecurityEvent.objects.create(actor=actor, event=event, success=success, ip_hash=SecurityEvent.hash_ip(client_ip(request)), metadata=safe_metadata)
        logger.info("event=%s success=%s actor=%s", event, success, getattr(actor, "pk", None))
    except Exception:
        logger.exception("audit_write_failed event=%s", event)


def allow_action(action, key, *, limit, window_seconds):
    key_hash = hashlib.sha256(f"{settings.SECRET_KEY}:{key}".encode()).hexdigest()
    now = timezone.now()
    epoch = int(now.timestamp())
    start = datetime.fromtimestamp(epoch - (epoch % window_seconds), tz=timezone.get_current_timezone())
    with transaction.atomic():
        bucket, _ = RateBucket.objects.select_for_update().get_or_create(action=action, key_hash=key_hash, window_start=start)
        if bucket.count >= limit:
            return False
        bucket.count += 1
        bucket.save(update_fields=["count"])
    return True
