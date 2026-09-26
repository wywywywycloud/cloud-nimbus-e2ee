"""Keep authentication material out of Django's error pages and error emails."""
import re

from django.views.debug import SafeExceptionReporterFilter


class NimbusExceptionReporterFilter(SafeExceptionReporterFilter):
    # OPAQUE's setup is secret, but its name does not match Django's default
    # KEY/SECRET/PASSWORD patterns. Cover settings and request META alike.
    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern
        + "|OPAQUE_SERVER_SETUP|OPAQUE_MODULE_PATH",
        re.IGNORECASE,
    )

    def is_active(self, request):
        # Development tracebacks must also honor sensitive_variables annotations
        # on the protocol bridge and authentication handlers.
        return True
