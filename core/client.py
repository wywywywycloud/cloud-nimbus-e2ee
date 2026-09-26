"""Serve the separately released client without rendering or injecting any bytes."""
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET


CLIENT_CSP = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
    "img-src 'self' blob: data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'; worker-src 'none'"
)
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".json": "application/json"}


@require_GET
def browser_client(request, asset="index.html"):
    root = Path(settings.CYPHER_CLIENT_ROOT).resolve()
    relative = Path(asset)
    if relative.is_absolute() or ".." in relative.parts or any(part.startswith(".") for part in relative.parts):
        raise Http404
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.suffix not in CONTENT_TYPES:
        raise Http404
    response = HttpResponse(target.read_bytes(), content_type=CONTENT_TYPES[target.suffix])
    response["Content-Security-Policy"] = CLIENT_CSP
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    response["X-Frame-Options"] = "DENY"
    return response
