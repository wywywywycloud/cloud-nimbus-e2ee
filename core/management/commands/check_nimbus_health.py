import shutil
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from drive.security import scanner_status


class Command(BaseCommand):
    help = "Check database, storage capacity and malware scanner readiness."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        media = Path(settings.MEDIA_ROOT)
        media.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(media)
        scanner = scanner_status()
        self.stdout.write(f"database=ok storage_free_bytes={disk.free} scanner_available={scanner['available']}")
        if settings.MALWARE_SCAN_REQUIRED and not scanner["available"]:
            raise CommandError("Malware scanner is required but unavailable")
