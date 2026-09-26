from django.utils.translation import gettext_lazy as _


# Russian is the product default. The remaining entries are the 24 official
# EU languages plus the explicitly supported Arabic, Urdu and Hindi locales.
SUPPORTED_LANGUAGES = (
    ("ru", _("Русский")),
    ("bg", _("Български")),
    ("hr", _("Hrvatski")),
    ("cs", _("Čeština")),
    ("da", _("Dansk")),
    ("nl", _("Nederlands")),
    ("en", _("English")),
    ("et", _("Eesti")),
    ("fi", _("Suomi")),
    ("fr", _("Français")),
    ("de", _("Deutsch")),
    ("el", _("Ελληνικά")),
    ("hu", _("Magyar")),
    ("ga", _("Gaeilge")),
    ("it", _("Italiano")),
    ("lv", _("Latviešu")),
    ("lt", _("Lietuvių")),
    ("mt", _("Malti")),
    ("pl", _("Polski")),
    ("pt", _("Português")),
    ("ro", _("Română")),
    ("sk", _("Slovenčina")),
    ("sl", _("Slovenščina")),
    ("es", _("Español")),
    ("sv", _("Svenska")),
    ("ar", _("العربية")),
    ("ur", _("اردو")),
    ("hi", _("हिन्दी")),
)

SUPPORTED_LANGUAGE_CODES = frozenset(code for code, _name in SUPPORTED_LANGUAGES)
RTL_LANGUAGE_CODES = frozenset({"ar", "ur"})
