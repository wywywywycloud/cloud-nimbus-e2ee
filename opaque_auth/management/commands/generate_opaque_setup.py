import os

from django.core.management.base import BaseCommand, CommandError

from opaque_auth.protocol import OpaqueError, call_opaque


class Command(BaseCommand):
    help = "Generate a new OPAQUE setup in a new private environment file. Never overwrite an existing setup."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="New private file outside version control.")

    def handle(self, *args, **options):
        try:
            value = call_opaque("createSetup")["serverSetup"]
            descriptor = os.open(options["output"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as target:
                target.write(f"OPAQUE_SERVER_SETUP={value}\n")
        except (OpaqueError, OSError):
            raise CommandError("Could not create OPAQUE setup; check runtime configuration and use a new private output path.") from None
        self.stdout.write("OPAQUE setup written to the requested private file. Back it up; replacing it invalidates existing credentials.")
