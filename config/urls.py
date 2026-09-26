from django.contrib import admin
from django.urls import include, path
from accounts.views import admin_login_redirect
from core.client import browser_client


urlpatterns = [
    path("vault/", browser_client, name="browser_client"),
    path("vault/<path:asset>", browser_client, name="browser_client_asset"),
    path("admin/login/", admin_login_redirect, name="admin_login"),
    path("admin/", admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("api/cypher/", include("vaults.urls")),
    path("api/opaque/", include("opaque_auth.urls")),
    path("api/passkeys/", include("passkeys.urls")),
    path("api/otp/", include("otp_auth.urls")),
    path("", include("sharing.urls")),
    path("", include("core.urls")),
    path("", include("drive.urls")),
]
