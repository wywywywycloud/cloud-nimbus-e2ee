from datetime import timedelta

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from .models import BlobDeletion, CipherFile


def cleanup_blob(job_id, *, force=False):
    """Delete idempotently; storage failures never undo logical revocation."""
    with transaction.atomic():
        job = BlobDeletion.objects.select_for_update().filter(pk=job_id).first()
        if job is None or (not force and job.not_before > timezone.now()):
            return False
        if CipherFile.objects.filter(storage_key=job.storage_key).exists():
            # A published object's data must never be deleted by a stale job.
            job.delete()
            return False
        try:
            default_storage.delete(job.storage_key)
        except Exception as exc:
            job.attempts += 1
            job.last_error = type(exc).__name__[:128]
            job.not_before = timezone.now() + timedelta(minutes=5)
            job.save(update_fields=["attempts", "last_error", "not_before"])
            return False
        job.delete()
        return True


def queue_blob_deletion(storage_key):
    job, _ = BlobDeletion.objects.update_or_create(storage_key=storage_key, defaults={"not_before": timezone.now()})
    transaction.on_commit(lambda job_id=job.pk: cleanup_blob(job_id), robust=True)
    return job
