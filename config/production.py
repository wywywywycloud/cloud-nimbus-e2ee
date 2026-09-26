"""Single-host deployment behind the local TLS-terminating Nginx proxy."""
import ipaddress
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

if DEBUG or DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Production requires DEBUG=0 and PostgreSQL")
if not OPAQUE_SERVER_SETUP or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Production requires persistent OPAQUE setup and Django secret")
origin = urlsplit(PASSKEY_ORIGIN)
if (origin.scheme != "https" or not (origin.hostname == PASSKEY_RP_ID or (origin.hostname or "").endswith("." + PASSKEY_RP_ID))
        or origin.port != 9443 or origin.path or origin.query or origin.fragment
        or origin.username or origin.password or origin.hostname not in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Set an HTTPS origin on port 9443, its allowed host and matching DNS RP ID (or parent domain)")
try:
    ipaddress.ip_address(PASSKEY_RP_ID)
except ValueError:
    pass
else:
    raise ImproperlyConfigured("WebAuthn requires a DNS name, not an IP address")
if NIMBUS_LEGACY_WRITES_ENABLED or not TELEGRAM_ENABLED or not OPAQUE_ENABLED or not PASSKEY_REQUIRED or not LOGIN_SECOND_FACTOR_REQUIRED:
    raise ImproperlyConfigured("Production E2EE authentication policy must remain enabled")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_BOT_USERNAME:
    raise ImproperlyConfigured("Configure the Telegram bot before starting production")
# Email verification/recovery is disabled by the authentication boundary.
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"

# Safe only because Gunicorn listens on loopback and Nginx overwrites this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [PASSKEY_ORIGIN]
SECURE_SSL_HOST = origin.netloc
# Do not change HSTS policy for unrelated services on this domain/subdomains.
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# HSTS is host-wide and cannot be scoped to :9443. This is an explicit policy.
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W005", "security.W021"]
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
FILE_UPLOAD_MAX_MEMORY_SIZE = 0
FILE_UPLOAD_TEMP_DIR = os.environ.get("DJANGO_UPLOAD_TEMP_DIR", "/var/lib/nimbus/tmp")
