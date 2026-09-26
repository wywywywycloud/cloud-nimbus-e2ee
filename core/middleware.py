from .audit import audit


class SecurityAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code >= 500:
            audit(request, "http.server_error", success=False, status=response.status_code)
        response.setdefault("Referrer-Policy", "same-origin")
        return response
