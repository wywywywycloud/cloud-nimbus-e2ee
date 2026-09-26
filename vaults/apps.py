from django.apps import AppConfig


class VaultsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vaults"

    def ready(self):
        from . import signals  # noqa: F401
