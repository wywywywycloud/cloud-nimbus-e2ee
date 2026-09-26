from django.core.management.base import BaseCommand
from drive.models import StoredFile
from drive.security import scan_path


class Command(BaseCommand):
    help = "Rescan pending or failed local files with ClamAV."

    def handle(self, *args, **options):
        scanned = 0
        for item in StoredFile.objects.filter(storage_backend=StoredFile.StorageBackend.LOCAL, scan_status__in=[StoredFile.ScanStatus.PENDING, StoredFile.ScanStatus.ERROR]):
            status, report, checksum = scan_path(item.blob.path)
            item.scan_status = status
            item.scan_report = report
            item.checksum_sha256 = checksum
            item.object_key = item.blob.name
            item.save(update_fields=["scan_status", "scan_report", "checksum_sha256", "object_key", "updated_at"])
            scanned += 1
        self.stdout.write(self.style.SUCCESS(f"Scanned {scanned} files"))
