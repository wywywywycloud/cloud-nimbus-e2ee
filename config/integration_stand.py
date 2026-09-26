"""Isolated integration stand. Never select this settings module in production."""
from .settings import *  # noqa: F403

EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = os.environ["NIMBUS_TEST_EMAIL_DIR"]

