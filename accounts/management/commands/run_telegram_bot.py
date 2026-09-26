import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.telegram import TelegramAPIError, api_call, handle_update


class Command(BaseCommand):
    help = "Run the cloud.nimbus Telegram bot using long polling (useful for localhost)."

    def handle(self, *args, **options):
        if not settings.TELEGRAM_ENABLED:
            raise CommandError("Telegram integration is disabled (TELEGRAM_ENABLED=0).")
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_BOT_USERNAME:
            raise CommandError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME first.")
        self.stdout.write(self.style.SUCCESS(f"Telegram bot @{settings.TELEGRAM_BOT_USERNAME} is polling."))
        offset = 0
        try:
            while True:
                try:
                    # Keep localhost polling requests short. Some desktop/VPN
                    # proxies terminate Telegram's long-held HTTP connection
                    # before Telegram returns, leaving valid updates queued.
                    updates = api_call("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message"]}, timeout=10)
                    for update in updates:
                        offset = max(offset, update["update_id"] + 1)
                        handle_update(update)
                    if not updates:
                        time.sleep(1)
                except TelegramAPIError as exc:
                    self.stderr.write(str(exc))
                    time.sleep(3)
        except KeyboardInterrupt:
            self.stdout.write("Telegram bot stopped.")
