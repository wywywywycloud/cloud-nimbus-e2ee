from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from core.models import SecurityEvent


class Command(BaseCommand):
    help = "Permanently purge accounts whose 30-day recovery period has expired."

    def handle(self, *args, **options):
        purged = 0
        for user_id in User.objects.filter(is_active=False, scheduled_deletion_at__lte=timezone.now()).values_list("pk", flat=True):
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=user_id)
                files = list(user.stored_files.all())
                failed = False
                for item in files:
                    try:
                        item.blob.delete(save=False)
                    except Exception as exc:
                        failed = True
                        self.stderr.write(f"Could not delete blob for file {item.pk}: {type(exc).__name__}")
                if failed:
                    continue
                SecurityEvent.objects.filter(actor=user).update(actor=None)
                user.delete()
                purged += 1
        self.stdout.write(self.style.SUCCESS(f"Purged {purged} accounts"))
