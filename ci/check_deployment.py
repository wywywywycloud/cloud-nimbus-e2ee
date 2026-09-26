#!/usr/bin/env python3
"""Local configuration/readiness checks with disposable secrets, DB and storage."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import json

ROOT = Path(__file__).resolve().parents[1]


def run(args, env, succeeds=True):
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    if (result.returncode == 0) != succeeds:
        # Do not print subprocess output: configuration errors may contain secrets.
        raise AssertionError(f"Unexpected exit status for {args[:3]}: {result.returncode}")
    return result


def main():
    for name in ("nimbus-release", "nimbus-backup", "nimbus-backup-data", "nimbus-ssh-deploy"):
        run(["bash", "-n", str(ROOT / "deploy" / name)], os.environ)
    with tempfile.TemporaryDirectory(prefix="nimbus-deployment-check-") as directory:
        work = Path(directory)
        media = work / "media"
        media.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("POSTGRES_", "DJANGO_", "OPAQUE_", "PASSKEY_", "CYPHER_"))}
        env.update(DJANGO_SETTINGS_MODULE="config.settings", DJANGO_DEBUG="1",
                   DJANGO_DATABASE_PATH=str(work / "db.sqlite3"), DJANGO_MEDIA_ROOT=str(media),
                   OPAQUE_NODE=os.environ.get("OPAQUE_NODE", "node"))
        # createSetup consumes stdin, so invoke explicitly without logging output.
        setup = subprocess.run([env["OPAQUE_NODE"], "opaque_auth/bridge.mjs"], input='{"action":"createSetup"}',
                               cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        env["OPAQUE_SERVER_SETUP"] = json.loads(setup.stdout)["result"]["serverSetup"]
        run([sys.executable, "manage.py", "migrate", "--noinput"], env)
        run([sys.executable, "manage.py", "deployment_check"], env)
        run([sys.executable, "manage.py", "deployment_check"], dict(env, OPAQUE_SERVER_SETUP="invalid"), False)
        run([sys.executable, "manage.py", "deployment_check"], dict(env, CYPHER_CLIENT_ROOT=str(work / "absent")), False)
        production = dict(env, DJANGO_SETTINGS_MODULE="config.production", DJANGO_DEBUG="0",
                          DJANGO_SECRET_KEY=os.urandom(32).hex(), DJANGO_ALLOWED_HOSTS="nimbus.by",
                          DJANGO_UPLOAD_TEMP_DIR=str(work),
                          POSTGRES_DB="nimbus_ci", PASSKEY_RP_ID="nimbus.by", PASSKEY_ORIGIN="https://nimbus.by:9443",
                          TELEGRAM_ENABLED="1", TELEGRAM_BOT_TOKEN="synthetic-test-only",
                          TELEGRAM_BOT_USERNAME="synthetic_test_bot", PASSKEY_REQUIRED="1",
                          LOGIN_SECOND_FACTOR_REQUIRED="1", NIMBUS_LEGACY_WRITES_ENABLED="0", OPAQUE_ENABLED="1")
        command = [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"]
        run(command, production)
        for changes in ({"DJANGO_DEBUG": "1"}, {"POSTGRES_DB": ""}, {"TELEGRAM_ENABLED": "0"},
                        {"TELEGRAM_BOT_TOKEN": ""}, {"PASSKEY_ORIGIN": "https://nimbus.by"},
                        {"PASSKEY_REQUIRED": "0"}, {"LOGIN_SECOND_FACTOR_REQUIRED": "0"},
                        {"NIMBUS_LEGACY_WRITES_ENABLED": "1"}, {"OPAQUE_SERVER_SETUP": ""}):
            run(command, dict(production, **changes), False)
    print("Deployment shell syntax, disposable readiness and production guards passed")


if __name__ == "__main__":
    main()
