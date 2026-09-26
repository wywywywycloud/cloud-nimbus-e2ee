from django.contrib import admin
from .models import Folder, StoredFile, UploadSession


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "parent", "updated_at")
    search_fields = ("name", "owner__username", "owner__email")
    readonly_fields = ("owner", "parent", "name", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "owner", "size", "scan_status", "favorite", "updated_at")
    list_filter = ("scan_status", "favorite", "updated_at")
    search_fields = ("display_name", "owner__username", "owner__email")
    fields = (
        "display_name",
        "owner",
        "size",
        "content_type",
        "scan_status",
        "scan_report",
        "checksum_sha256",
        "storage_backend",
        "provider_version",
        "favorite",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "display_name", "total_size", "backend", "state", "expires_at")
    list_filter = ("backend", "state", "expires_at")
    search_fields = ("id", "owner__username", "owner__email", "display_name")
    readonly_fields = (
        "id",
        "owner",
        "display_name",
        "content_type",
        "total_size",
        "chunk_size",
        "received_parts",
        "backend",
        "backend_upload_id",
        "idempotency_key",
        "state",
        "expires_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_delete_permission(self, request, obj=None):
        return False
