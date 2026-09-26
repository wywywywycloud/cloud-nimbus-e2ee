import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def offer(request):
    return render(request, "core/offer.html")


def privacy(request):
    return render(request, "core/privacy.html")


def health(request):
    return JsonResponse({"status": "ok"})


@staff_member_required
def readiness(request):
    from drive.security import scanner_status
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    media = Path(settings.MEDIA_ROOT)
    media.mkdir(parents=True, exist_ok=True)
    storage_ok = media.exists() and os_access_write(media)
    scanner = scanner_status()
    healthy = db_ok and storage_ok and (scanner["available"] or not settings.MALWARE_SCAN_REQUIRED)
    return JsonResponse({"status": "ok" if healthy else "degraded", "database": db_ok, "storage": storage_ok, "malware_scanner": scanner}, status=200 if healthy else 503)


def os_access_write(path):
    import os
    return os.access(path, os.W_OK)


@staff_member_required
def metrics(request):
    from accounts.models import User
    from drive.models import StoredFile
    totals = {
        "users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "scheduled_deletions": User.objects.filter(scheduled_deletion_at__isnull=False).count(),
        "files": StoredFile.objects.count(),
        "clean_files": StoredFile.objects.filter(scan_status=StoredFile.ScanStatus.CLEAN).count(),
        "quarantined_files": StoredFile.objects.filter(scan_status=StoredFile.ScanStatus.INFECTED).count(),
        "stored_bytes": sum(User.objects.values_list("used_bytes", flat=True)),
        "disk_free_bytes": shutil.disk_usage(settings.MEDIA_ROOT).free if Path(settings.MEDIA_ROOT).exists() else None,
    }
    return JsonResponse(totals)
