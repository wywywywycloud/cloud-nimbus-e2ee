from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import OneTimeCode, TelegramLinkAttempt, User


@admin.register(User)
class CloudUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("cloud.nimbus", {"fields": ("email_verified", "auth_mode", "ui_theme", "language", "used_bytes", "reserved_bytes", "quota_bytes", "telegram_user_id", "telegram_username", "telegram_first_name", "telegram_linked_at", "scheduled_deletion_at")}),)
    readonly_fields = ("used_bytes", "reserved_bytes", "telegram_linked_at", "scheduled_deletion_at")


@admin.register(OneTimeCode)
class OneTimeCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "created_at", "expires_at", "consumed_at", "attempts")
    readonly_fields = ("digest",)


@admin.register(TelegramLinkAttempt)
class TelegramLinkAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at", "telegram_sender_id")
    readonly_fields = ("token_digest", "created_at", "used_at")
