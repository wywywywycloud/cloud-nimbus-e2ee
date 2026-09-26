from django.urls import path
from . import views

app_name = "drive"

urlpatterns = [
    path("", views.home, name="home"),
    path("folders/create/", views.create_folder, name="folder_create"),
    path("folders/<int:folder_id>/", views.folder, name="folder"),
    path("folders/<int:pk>/rename/", views.rename_folder, name="folder_rename"),
    path("folders/<int:pk>/delete/", views.delete_folder, name="folder_delete"),
    path("upload/", views.upload, name="upload"),
    path("files/<int:pk>/download/", views.download, name="download"),
    path("files/<int:pk>/preview/", views.preview, name="preview"),
    path("files/<int:pk>/rename/", views.rename, name="rename"),
    path("files/<int:pk>/favorite/", views.favorite, name="favorite"),
    path("files/<int:pk>/delete/", views.delete, name="delete"),
    path("api/uploads/initiate/", views.upload_initiate, name="upload_initiate"),
    path("api/uploads/<uuid:upload_id>/", views.upload_status, name="upload_status"),
    path("api/uploads/<uuid:upload_id>/parts/<int:part_number>/", views.upload_part, name="upload_part"),
    path("api/uploads/<uuid:upload_id>/complete/", views.upload_complete, name="upload_complete"),
    path("api/uploads/<uuid:upload_id>/abort/", views.upload_abort, name="upload_abort"),
]
