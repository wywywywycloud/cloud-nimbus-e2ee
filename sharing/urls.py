from django.urls import path

from . import views

app_name = "sharing"

urlpatterns = [
    path("shared/", views.shared_with_me, name="shared_with_me"),
    path("sharing/api/<str:kind>/<int:item_id>/", views.item_share_state, name="item_state"),
    path("sharing/api/<str:kind>/<int:item_id>/general/", views.set_general_access, name="item_general"),
    path("sharing/api/<str:kind>/<int:item_id>/grants/", views.create_item_grant, name="item_grant"),
    path("sharing/files/<int:file_id>/", views.file_shares, name="file_shares"),
    path("sharing/files/<int:file_id>/create/", views.create_share, name="create"),
    path("sharing/files/<int:file_id>/revoke-all/", views.revoke_all_share_links, name="revoke_all"),
    path("sharing/files/<int:file_id>/grants/create/", views.create_grant, name="create_grant"),
    path("sharing/grants/<int:pk>/revoke/", views.revoke_grant, name="revoke_grant"),
    path("sharing/links/<uuid:pk>/update/", views.update_share, name="update"),
    path("sharing/links/<uuid:pk>/revoke/", views.revoke_share_link, name="revoke"),
    path("s/<str:token>/", views.public_share, name="public_share"),
    path("s/<str:token>/folders/<int:folder_id>/", views.public_share_folder, name="public_share_folder"),
    path("s/<str:token>/files/<int:file_id>/", views.public_share_file, name="public_share_file"),
]
