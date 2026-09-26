from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, register


class OpaqueAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "opaque_auth"


@register()
def check_opaque_sessions(app_configs, **kwargs):
    if settings.OPAQUE_ENABLED and settings.SESSION_ENGINE == "django.contrib.sessions.backends.signed_cookies":
        return [Error("OPAQUE requires server-side Django sessions.", id="opaque_auth.E001")]
    return []
