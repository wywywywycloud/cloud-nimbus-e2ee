"""Private readiness check for the E2EE deployment; emits no protocol material."""
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from opaque_auth.protocol import call_opaque


class Command(BaseCommand):
    help = "Verify metadata database, private blob storage and OPAQUE runtime"

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM django_migrations LIMIT 1")
                cursor.fetchone()
            with tempfile.TemporaryFile(dir=settings.MEDIA_ROOT) as probe:
                probe.write(b"readiness")
                probe.flush()
            if not (Path(settings.CYPHER_CLIENT_ROOT) / "index.html").is_file():
                raise ValueError("client missing")
            call_opaque("getPublicKey")
        except Exception:
            raise CommandError("E2EE readiness failed; inspect configuration privately") from None
        self.stdout.write("Database, private storage, client and OPAQUE runtime ready")
