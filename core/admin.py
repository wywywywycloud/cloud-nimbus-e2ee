from django.contrib import admin
from .models import RateBucket, SecurityEvent


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "actor", "success", "ip_hash_short")
    list_filter = ("success", "event", "created_at")
    search_fields = ("event", "actor__username", "actor__email")
    readonly_fields = ("actor", "event", "success", "ip_hash", "metadata", "created_at")
    date_hierarchy = "created_at"

    def ip_hash_short(self, obj):
        return obj.ip_hash[:10]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RateBucket)
class RateBucketAdmin(admin.ModelAdmin):
    list_display = ("action", "key_hash", "window_start", "count")
    readonly_fields = ("action", "key_hash", "window_start", "count")
