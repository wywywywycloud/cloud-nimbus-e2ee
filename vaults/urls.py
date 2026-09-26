from django.urls import path

from . import views

app_name = "vaults"

urlpatterns = [
    path("session/", views.session, name="session"),
    path("vault/", views.create_vault, name="create_vault"),
    path("files/", views.files, name="files"),
    path("files/<uuid:file_id>/download/", views.download, name="download"),
    path("files/<uuid:file_id>/", views.delete_file, name="delete_file"),
    path("reset/", views.reset, name="reset"),
]
