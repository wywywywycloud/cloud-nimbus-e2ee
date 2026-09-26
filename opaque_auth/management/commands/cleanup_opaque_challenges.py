from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from opaque_auth.models import OpaqueChallenge


class Command(BaseCommand):
    help = "Delete consumed and expired OPAQUE exchange state."

    def handle(self, *args, **options):
        deleted, _ = OpaqueChallenge.objects.filter(Q(expires_at__lte=timezone.now()) | Q(consumed_at__isnull=False)).delete()
        self.stdout.write(f"Deleted {deleted} OPAQUE challenges.")
