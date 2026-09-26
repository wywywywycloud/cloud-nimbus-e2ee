from django.conf import settings
from django.utils import translation

from .i18n import RTL_LANGUAGE_CODES, SUPPORTED_LANGUAGE_CODES


class UserPreferencesMiddleware:
    """Apply persisted UI preferences after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        default_language = settings.LANGUAGE_CODE.split("-", 1)[0]
        language = request.session.get("django_language", default_language)
        theme = request.session.get("ui_theme", "dark")

        if request.user.is_authenticated:
            language = request.user.language
            theme = request.user.ui_theme
            # Keeping these values in session makes the preference effective on
            # the logout response and gives LocaleMiddleware a stable fallback.
            request.session["django_language"] = language
            request.session["ui_theme"] = theme

        if language not in SUPPORTED_LANGUAGE_CODES:
            language = default_language
        if theme not in {"dark", "light"}:
            theme = "dark"

        translation.activate(language)
        request.LANGUAGE_CODE = language
        request.ui_theme = theme
        request.language_direction = "rtl" if language in RTL_LANGUAGE_CODES else "ltr"
        return self.get_response(request)
