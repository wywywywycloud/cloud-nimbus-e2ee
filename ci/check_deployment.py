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


def check_production(env, work):
    """Check production guards without requiring Linux services or a database."""
    production = dict(env, DJANGO_SETTINGS_MODULE="config.production", DJANGO_DEBUG="0",
                      DJANGO_SECRET_KEY=os.urandom(32).hex(), DJANGO_ALLOWED_HOSTS="cloud.nimbus.by",
                      DJANGO_UPLOAD_TEMP_DIR=str(work),
                      POSTGRES_DB="nimbus_ci", PASSKEY_RP_ID="nimbus.by", PASSKEY_ORIGIN="https://cloud.nimbus.by",
                      TELEGRAM_ENABLED="1", TELEGRAM_BOT_TOKEN="synthetic-test-only",
                      TELEGRAM_BOT_USERNAME="synthetic_test_bot", PASSKEY_REQUIRED="1",
                      LOGIN_SECOND_FACTOR_REQUIRED="1", NIMBUS_LEGACY_WRITES_ENABLED="0", OPAQUE_ENABLED="1")
    command = [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"]
    run(command, production)
    # Exercise redirects and CSRF with the actual production settings, no DB.
    run([sys.executable, "-c", """
import django
django.setup()
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory
factory = RequestFactory()
view = lambda request: HttpResponse('ok')
request = factory.get('/vault/?next=a%2Fb', HTTP_HOST='cloud.nimbus.by')
response = SecurityMiddleware(view).process_request(request)
assert response['Location'] == 'https://cloud.nimbus.by/vault/?next=a%2Fb'
request.META['HTTP_X_FORWARDED_PROTO'] = 'https'
assert SecurityMiddleware(view).process_request(request) is None
for origin, allowed in [('https://cloud.nimbus.by', True),
                        ('https://cloud.nimbus.by:9443', False),
                        ('https://attacker.test', False)]:
    request = factory.post('/api/opaque/register/start/', HTTP_HOST='cloud.nimbus.by',
                           HTTP_X_FORWARDED_PROTO='https', HTTP_ORIGIN=origin)
    request.META['HTTP_X_CSRFTOKEN'] = get_token(request)
    request.COOKIES[settings.CSRF_COOKIE_NAME] = request.META['CSRF_COOKIE']
    middleware = CsrfViewMiddleware(view)
    middleware.process_request(request)
    response = middleware.process_view(request, view, (), {})
    assert (response is None) == allowed
    if response is not None:
        assert response.status_code == 403
"""], production)
    # A parent RP preserves existing credentials when moving to a subdomain.
    for changes in ({"PASSKEY_RP_ID": "cloud.nimbus.by"},
                    {"PASSKEY_ORIGIN": "https://nimbus.by", "DJANGO_ALLOWED_HOSTS": "nimbus.by"}):
        run(command, dict(production, **changes))
    for changes in ({"DJANGO_DEBUG": "1"}, {"POSTGRES_DB": ""}, {"TELEGRAM_ENABLED": "0"},
                    {"TELEGRAM_BOT_TOKEN": ""}, {"PASSKEY_ORIGIN": "http://cloud.nimbus.by"},
                    {"PASSKEY_ORIGIN": "https://cloud.nimbus.by:8000"},
                    {"PASSKEY_ORIGIN": "https://cloud.nimbus.by:443"},
                    {"PASSKEY_ORIGIN": "https://cloud.nimbus.by:9443"},
                    {"PASSKEY_ORIGIN": "https://cloud.nimbus.by/"},
                    {"PASSKEY_ORIGIN": "https://cloud.nimbus.by?query=1"},
                    {"PASSKEY_ORIGIN": "https://cloud.nimbus.by#fragment"},
                    {"PASSKEY_ORIGIN": "https://user:password@cloud.nimbus.by"},
                    {"PASSKEY_RP_ID": "other.nimbus.by"},
                    {"PASSKEY_RP_ID": "imbus.by"},
                    {"PASSKEY_ORIGIN": "https://evilnimbus.by", "DJANGO_ALLOWED_HOSTS": "evilnimbus.by"},
                    {"PASSKEY_ORIGIN": "https://nimbus.by.evil.test", "DJANGO_ALLOWED_HOSTS": "nimbus.by.evil.test"},
                    {"DJANGO_ALLOWED_HOSTS": "nimbus.by"},
                    {"PASSKEY_REQUIRED": "0"}, {"LOGIN_SECOND_FACTOR_REQUIRED": "0"},
                    {"NIMBUS_LEGACY_WRITES_ENABLED": "1"}, {"OPAQUE_SERVER_SETUP": ""}):
        run(command, dict(production, **changes), False)


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
        check_production(env, work)
    print("Deployment shell syntax, disposable readiness and production guards passed")


if __name__ == "__main__":
    main()
