from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import RateBucket


class Command(BaseCommand):
    help = "Delete expired authentication rate-limit buckets."

    def handle(self, *args, **options):
        deleted, _ = RateBucket.objects.filter(window_start__lt=timezone.now() - timedelta(days=2)).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} rate buckets"))
