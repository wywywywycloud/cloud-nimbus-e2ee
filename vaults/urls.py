from django.urls import path

from . import views
from . import organize

app_name = "vaults"

urlpatterns = [
    path("passkey/skip/", views.skip_passkey, name="skip_passkey"),
    path("session/", views.session, name="session"),
    path("vault/", views.create_vault, name="create_vault"),
    path("files/", views.files, name="files"),
    path("folders/", organize.folders, name="folders"),
    path("items/<str:kind>/<uuid:identifier>/", organize.item, name="item"),
    path("files/<uuid:file_id>/download/", views.download, name="download"),
    path("files/<uuid:file_id>/", views.delete_file, name="delete_file"),
    path("reset/", views.reset, name="reset"),
]
