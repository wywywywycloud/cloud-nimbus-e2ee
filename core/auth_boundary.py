"""Keep the legacy plaintext password forms outside the E2EE deployment."""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect


class BrowserAuthBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        legacy = request.path in {"/auth/login/", "/auth/register/", "/auth/login/code/", "/auth/login/code/resend/"} or request.path.startswith("/auth/password-reset/")
        if getattr(settings, "OPAQUE_ENABLED", True) and legacy:
            if request.method in {"GET", "HEAD"}:
                return redirect("/vault/")
            return JsonResponse({"error": "use_opaque_or_passkey", "client": "/vault/"}, status=410)
        return self.get_response(request)
