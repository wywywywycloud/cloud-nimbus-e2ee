from pathlib import Path
import os

from accounts.i18n import SUPPORTED_LANGUAGES


BASE_DIR = Path(__file__).resolve().parent.parent
_telegram_env_file = BASE_DIR / ".env.telegram"
if _telegram_env_file.exists():
    for _line in _telegram_env_file.read_text(encoding="utf-8").splitlines():
        _name, _separator, _value = _line.partition("=")
        if _separator and _name in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_WEBHOOK_SECRET"}:
            os.environ.setdefault(_name, _value.strip())
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me-cloud-nimbus")
if not DEBUG and "DJANGO_SECRET_KEY" not in os.environ:
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=0")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "drive",
    "core",
    "sharing",
    "vaults",
    "opaque_auth",
    "passkeys",
    "otp_auth",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.auth_boundary.BrowserAuthBoundaryMiddleware",
    "accounts.middleware.UserPreferencesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.SecurityAuditMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "drive.context_processors.storage_usage",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("DJANGO_DATABASE_PATH", BASE_DIR / "db.sqlite3")}}
if os.environ.get("POSTGRES_DB"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", "nimbus"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", ""),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
LANGUAGES = SUPPORTED_LANGUAGES
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

# The separately licensed browser client is served byte-for-byte, without templates.
CYPHER_CLIENT_ROOT = Path(os.environ.get("CYPHER_CLIENT_ROOT", BASE_DIR / "cloud-cypher" / "web"))
NIMBUS_LEGACY_WRITES_ENABLED = os.environ.get("NIMBUS_LEGACY_WRITES_ENABLED", "0") == "1"
TELEGRAM_ENABLED = os.environ.get("TELEGRAM_ENABLED", "0") == "1"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
OPAQUE_ENABLED = os.environ.get("OPAQUE_ENABLED", "1") == "1"
OPAQUE_NODE = os.environ.get("OPAQUE_NODE", "node")
OPAQUE_MODULE_PATH = os.environ.get("OPAQUE_MODULE_PATH", "")
OPAQUE_SERVER_SETUP = os.environ.get("OPAQUE_SERVER_SETUP", "")
DEFAULT_EXCEPTION_REPORTER_FILTER = "core.debug.NimbusExceptionReporterFilter"
PASSKEY_RP_ID = os.environ.get("PASSKEY_RP_ID", "localhost" if DEBUG else "")
PASSKEY_ORIGIN = os.environ.get("PASSKEY_ORIGIN", "http://localhost:8017" if DEBUG else "")
PASSKEY_REQUIRED = os.environ.get("PASSKEY_REQUIRED", "1") == "1"
LOGIN_SECOND_FACTOR_REQUIRED = os.environ.get("LOGIN_SECOND_FACTOR_REQUIRED", "1") == "1"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "drive:home"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_AGE = 60 * 60 * 24 * 90
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 55 * 1024 * 1024
MAX_SINGLE_UPLOAD_BYTES = int(os.environ.get("MAX_SINGLE_UPLOAD_BYTES", str(50 * 1024 * 1024)))
UPLOAD_CHUNK_BYTES = int(os.environ.get("UPLOAD_CHUNK_BYTES", str(5 * 1024 * 1024)))
MALWARE_SCAN_REQUIRED = os.environ.get("MALWARE_SCAN_REQUIRED", "0" if DEBUG else "1") == "1"
CLAMSCAN_PATH = os.environ.get("CLAMSCAN_PATH", "clamscan")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
TELEGRAM_LINK_TTL_SECONDS = int(os.environ.get("TELEGRAM_LINK_TTL_SECONDS", "900"))
TELEGRAM_VERIFIED_QUOTA_BYTES = int(os.environ.get("TELEGRAM_VERIFIED_QUOTA_BYTES", str(50 * 1024 * 1024)))

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "cloud.nimbus <noreply@localhost>")
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"format": '{{"time":"{asctime}","level":"{levelname}","logger":"{name}","message":"{message}"}}', "style": "{"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {
        # Warning-level request logs include full paths. Share capabilities live in
        # paths, so expected 404s must not leak them into application logs.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "cloud_nimbus.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
