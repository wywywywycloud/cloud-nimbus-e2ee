from django.core.management.base import BaseCommand
from django.utils import timezone

from vaults.models import BlobDeletion
from vaults.services import cleanup_blob


class Command(BaseCommand):
    help = "Retry ciphertext deletion and remove abandoned upload blobs."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        job_ids = list(BlobDeletion.objects.filter(not_before__lte=timezone.now()).order_by("not_before").values_list("pk", flat=True)[:max(0, options["limit"])])
        deleted = sum(cleanup_blob(job_id) for job_id in job_ids)
        self.stdout.write(f"Deleted {deleted} ciphertext blobs; {BlobDeletion.objects.count()} cleanup jobs remain.")
