from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from otp_auth.models import OtpChallenge


class Command(BaseCommand):
    help = "Delete consumed/expired login codes and pending TOTP setup secrets."

    def handle(self, *args, **options):
        count, _ = OtpChallenge.objects.filter(Q(consumed_at__isnull=False) | Q(expires_at__lte=timezone.now())).delete()
        self.stdout.write(f"Deleted {count} OTP challenges.")
