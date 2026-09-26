from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("verify-email/", views.verify_email_view, name="verify_email"),
    path("verify-email/resend/", views.resend_email_code_view, name="resend_email"),
    path("login/", views.login_view, name="login"),
    path("login/code/", views.verify_login_view, name="verify_login"),
    path("login/code/resend/", views.resend_login_code_view, name="resend_login"),
    path("remind-username/", views.username_reminder_view, name="remind_username"),
    path("settings/", views.settings_view, {"section": "account"}, name="settings"),
    path("settings/storage/", views.settings_view, {"section": "storage"}, name="storage_settings"),
    path("settings/interface/", views.settings_view, {"section": "interface"}, name="interface_settings"),
    path("telegram/link/", views.telegram_link_view, name="telegram_link"),
    path("telegram/status/", views.telegram_status_view, name="telegram_status"),
    path("telegram/webhook/", views.telegram_webhook_view, name="telegram_webhook"),
    path("delete-account/", views.delete_account_view, name="delete_account"),
    path("recover-account/<uidb64>/<token>/", views.recover_account_view, name="recover_account"),
    path("password-reset/", views.SafePasswordResetView.as_view(template_name="accounts/password_reset.html", email_template_name="accounts/password_reset_email.txt", subject_template_name="accounts/password_reset_subject.txt", success_url=reverse_lazy("accounts:password_reset_done")), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="accounts/password_reset_confirm.html", success_url=reverse_lazy("accounts:password_reset_complete")), name="password_reset_confirm"),
    path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
    path("logout/", views.logout_view, name="logout"),
]
