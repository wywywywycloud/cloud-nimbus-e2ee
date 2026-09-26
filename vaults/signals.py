from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import CipherFile
from .services import queue_blob_deletion


@receiver(post_delete, sender=CipherFile)
def delete_ciphertext_after_commit(sender, instance, **kwargs):
    # Also handles cascading deletion when the existing account purge runs.
    queue_blob_deletion(instance.storage_key)
