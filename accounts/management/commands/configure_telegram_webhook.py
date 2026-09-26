from urllib.parse import urljoin

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.telegram import api_call


class Command(BaseCommand):
    help = "Configure the Telegram webhook for a public HTTPS cloud.nimbus deployment."

    def add_arguments(self, parser):
        parser.add_argument("base_url", help="Public HTTPS base URL, for example https://cloud.example/")

    def handle(self, *args, **options):
        if not settings.TELEGRAM_ENABLED:
            raise CommandError("Telegram integration is disabled (TELEGRAM_ENABLED=0).")
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_BOT_USERNAME or not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError("Set TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME and TELEGRAM_WEBHOOK_SECRET first.")
        base_url = options["base_url"].rstrip("/") + "/"
        if not base_url.startswith("https://"):
            raise CommandError("Telegram webhooks require a public HTTPS URL.")
        webhook_url = urljoin(base_url, "auth/telegram/webhook/")
        api_call("setWebhook", {"url": webhook_url, "secret_token": settings.TELEGRAM_WEBHOOK_SECRET, "allowed_updates": ["message"]})
        self.stdout.write(self.style.SUCCESS(f"Webhook configured: {webhook_url}"))
