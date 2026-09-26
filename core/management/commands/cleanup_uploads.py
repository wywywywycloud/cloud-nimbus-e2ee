import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from drive.models import UploadSession


class Command(BaseCommand):
    help = "Abort expired resumable uploads and release quota reservations."

    def handle(self, *args, **options):
        count = 0
        active_states = (UploadSession.State.UPLOADING, UploadSession.State.ASSEMBLING)
        for upload_id in UploadSession.objects.filter(state__in=active_states, expires_at__lt=timezone.now()).values_list("pk", flat=True):
            with transaction.atomic():
                upload = UploadSession.objects.select_for_update().get(pk=upload_id)
                if upload.state not in active_states:
                    continue
                user = User.objects.select_for_update().get(pk=upload.owner_id)
                user.reserved_bytes = max(0, user.reserved_bytes - upload.total_size)
                user.save(update_fields=["reserved_bytes"])
                upload.state = UploadSession.State.ABORTED
                upload.save(update_fields=["state", "updated_at"])
            shutil.rmtree(Path(settings.MEDIA_ROOT) / "upload-parts" / str(upload.owner_id) / str(upload.pk), ignore_errors=True)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Aborted {count} expired uploads"))
