"""Isolated integration stand. Never select this settings module in production."""
from .settings import *  # noqa: F403

# This stand inspects its synthetic SQLite database directly, even in PostgreSQL CI.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ["DJANGO_DATABASE_PATH"]}}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
