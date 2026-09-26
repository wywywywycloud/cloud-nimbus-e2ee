from django.conf import settings


def storage_usage(request):
    if not request.user.is_authenticated:
        return {}
    used = request.user.used_bytes
    limit = request.user.quota_bytes
    telegram_quota_required = settings.TELEGRAM_ENABLED and not request.user.telegram_user_id
    display_limit = max(limit, settings.TELEGRAM_VERIFIED_QUOTA_BYTES) if telegram_quota_required else limit
    percent = min(100, used * 100 / display_limit) if display_limit else 0
    return {
        "storage_used_bytes": used,
        "storage_limit_bytes": limit,
        "storage_used_mb": used / 1024 / 1024,
        "storage_limit_mb": limit / 1024 / 1024,
        "storage_display_limit_mb": display_limit / 1024 / 1024,
        "storage_percent_css": f"{percent:.1f}",
        "telegram_quota_required": telegram_quota_required,
        "telegram_enabled": settings.TELEGRAM_ENABLED,
        "legacy_writes_enabled": settings.NIMBUS_LEGACY_WRITES_ENABLED,
        "opaque_enabled": getattr(settings, "OPAQUE_ENABLED", True),
    }
