from django.contrib import admin

from .models import FileGrant, ShareLink


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("target_name", "target_type", "owner", "access_mode", "active", "expires_at", "revision")
    list_filter = ("access_mode", "active")
    search_fields = ("file__display_name", "folder__name", "owner__username")

    @admin.display(description="Тип")
    def target_type(self, obj):
        return "Папка" if obj.folder_id else "Файл"


@admin.register(FileGrant)
class FileGrantAdmin(admin.ModelAdmin):
    list_display = ("target_name", "user", "email", "role", "granted_by")
    list_filter = ("role",)
    search_fields = ("file__display_name", "folder__name", "email", "user__username")

    @admin.display(description="Объект")
    def target_name(self, obj):
        return obj.folder.name if obj.folder_id else obj.file.display_name
