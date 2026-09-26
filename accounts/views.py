import hmac
import json
import secrets
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core import signing
from django.contrib.auth import views as auth_views
from django.core.mail import send_mail
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from datetime import timedelta

from core.audit import allow_action, audit, client_ip
from .forms import AuthModeForm, CodeForm, DeleteAccountForm, IdentifierForm, NotificationPreferencesForm, PasswordLoginForm, PreferencesForm, RegistrationForm, UsernameReminderForm, VerifiedPasswordResetForm
from .models import OneTimeCode, TelegramLinkAttempt
from .services import send_code, send_username_reminder
from .telegram import TelegramAPIError, handle_update

User = get_user_model()


def _remember_next(request):
    candidate = request.GET.get("next") or request.POST.get("next")
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        request.session["post_login_next"] = candidate


def _login_destination(request):
    return request.session.pop("post_login_next", None) or reverse("drive:home")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("drive:home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and not allow_action("register", client_ip(request), limit=5, window_seconds=3600):
        form.add_error(None, "Слишком много регистраций. Попробуйте позже.")
        audit(request, "registration.rate_limited", success=False)
    elif request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.email_verified = False
        user.is_active = False
        # The storage allocation exists immediately, but uploads stay locked
        # until the account is linked to the user's own Telegram account.
        user.quota_bytes = settings.TELEGRAM_VERIFIED_QUOTA_BYTES
        user.save()
        send_code(user, OneTimeCode.Purpose.VERIFY_EMAIL)
        request.session["verify_user_id"] = user.pk
        audit(request, "registration.started", actor=user)
        return redirect("accounts:verify_email")
    return render(request, "accounts/register.html", {"form": form})


def verify_email_view(request):
    user = User.objects.filter(pk=request.session.get("verify_user_id")).first()
    if not user:
        return redirect("accounts:register")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        otp = OneTimeCode.objects.filter(user=user, purpose=OneTimeCode.Purpose.VERIFY_EMAIL, consumed_at__isnull=True).order_by("-created_at").first()
        if otp and otp.verify(form.cleaned_data["code"]):
            user.email_verified = True
            user.is_active = True
            user.save(update_fields=["email_verified", "is_active"])
            request.session.pop("verify_user_id", None)
            login(request, user)
            audit(request, "registration.verified", actor=user)
            if settings.OPAQUE_ENABLED:
                messages.success(request, "Почта подтверждена. Войдите, чтобы открыть хранилище.")
                return redirect("browser_client")
            messages.success(request, "Почта подтверждена.")
            return redirect("accounts:settings")
        audit(request, "registration.code_failed", success=False, actor=user)
        form.add_error("code", "Код неверный или устарел.")
    return render(request, "accounts/verify.html", {"form": form, "email": user.email, "purpose": "verify"})


def resend_email_code_view(request):
    if request.method == "POST":
        user = User.objects.filter(pk=request.session.get("verify_user_id")).first()
        if user and allow_action("email_code", f"{client_ip(request)}:{user.pk}", limit=5, window_seconds=3600):
            sent = send_code(user, OneTimeCode.Purpose.VERIFY_EMAIL)
            messages.info(request, "Новый код отправлен." if sent else "Подождите минуту перед повторной отправкой.")
    return redirect("accounts:verify_email")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("drive:home")
    _remember_next(request)
    identifier = request.POST.get("identifier", "").strip()
    password_step = request.method == "POST" and (request.POST.get("password_step") == "1" or "password" in request.POST)
    form = PasswordLoginForm(request.POST) if password_step else IdentifierForm(request.POST or None)
    needs_password = password_step
    rate_key = f"{client_ip(request)}:{identifier.casefold()}"
    rate_action = "login_password" if password_step else "login_identifier"
    if request.method == "POST" and not allow_action(rate_action, rate_key, limit=10, window_seconds=900):
        form.add_error(None, "Слишком много попыток. Попробуйте через 15 минут.")
        audit(request, "login.rate_limited", success=False)
    elif request.method == "POST" and form.is_valid():
        user = form.user
        if not password_step and user.auth_mode in {User.AuthMode.PASSWORD, User.AuthMode.CODE_PASSWORD}:
            # Mode discovery is a real first step, not a failed password
            # submission. Render a clean form so the user never sees a bogus
            # "required" error before they had a password field.
            form = PasswordLoginForm(initial={"identifier": identifier})
            needs_password = True
            return render(request, "accounts/login.html", {"form": form, "show_password": True})
        if user.auth_mode == User.AuthMode.PASSWORD:
            login(request, user)
            audit(request, "login.password", actor=user)
            return redirect(_login_destination(request))
        request.session["login_user_id"] = user.pk
        send_code(user, OneTimeCode.Purpose.LOGIN)
        audit(request, "login.code_sent", actor=user)
        return redirect("accounts:verify_login")
    elif request.method == "POST":
        audit(request, "login.failed", success=False)
    return render(request, "accounts/login.html", {"form": form, "show_password": needs_password})


def verify_login_view(request):
    user = User.objects.filter(pk=request.session.get("login_user_id"), is_active=True).first()
    if not user:
        return redirect("accounts:login")
    form = CodeForm(request.POST or None)
    if request.method == "POST" and not allow_action("otp_verify", f"{client_ip(request)}:{user.pk}", limit=10, window_seconds=3600):
        form.add_error("code", "Слишком много попыток. Попробуйте позже.")
    elif request.method == "POST" and form.is_valid():
        otp = OneTimeCode.objects.filter(user=user, purpose=OneTimeCode.Purpose.LOGIN, consumed_at__isnull=True).order_by("-created_at").first()
        if otp and otp.verify(form.cleaned_data["code"]):
            request.session.pop("login_user_id", None)
            login(request, user)
            audit(request, "login.code", actor=user)
            return redirect(_login_destination(request))
        audit(request, "login.code_failed", success=False, actor=user)
        form.add_error("code", "Код неверный или устарел.")
    return render(request, "accounts/verify.html", {"form": form, "email": user.email, "purpose": "login"})


def resend_login_code_view(request):
    if request.method == "POST":
        user = User.objects.filter(pk=request.session.get("login_user_id"), is_active=True).first()
        if user and allow_action("login_code", f"{client_ip(request)}:{user.pk}", limit=5, window_seconds=3600):
            sent = send_code(user, OneTimeCode.Purpose.LOGIN)
            messages.info(request, "Новый код отправлен." if sent else "Подождите минуту перед повторной отправкой.")
    return redirect("accounts:verify_login")


def username_reminder_view(request):
    form = UsernameReminderForm(request.POST or None)
    key = f"{client_ip(request)}:{request.POST.get('email', '').casefold()}"
    if request.method == "POST" and not allow_action("username_reminder", key, limit=3, window_seconds=3600):
        messages.success(request, "Если аккаунт существует, логин отправлен на почту.")
        return redirect("accounts:login")
    if request.method == "POST" and form.is_valid():
        user = User.objects.filter(email__iexact=form.cleaned_data["email"], email_verified=True, is_active=True).first()
        if user:
            send_username_reminder(user)
        messages.success(request, "Если аккаунт существует, логин отправлен на почту.")
        return redirect("accounts:login")
    return render(request, "accounts/remind_username.html", {"form": form})


@login_required
def settings_view(request, section="account"):
    if request.method == "POST" and request.POST.get("action", "auth_mode") == "auth_mode":
        return JsonResponse({"error": "use_opaque_or_passkey", "client": "/vault/"}, status=410)
    if section not in {"account", "storage", "interface"}:
        return HttpResponseBadRequest("Неизвестный раздел настроек")

    action = request.POST.get("action", "")
    form = AuthModeForm(request.POST if request.method == "POST" and action == "auth_mode" else None, instance=request.user)
    preferences_form = PreferencesForm(request.POST if request.method == "POST" and action == "preferences" else None, instance=request.user)
    notifications_form = NotificationPreferencesForm(request.POST if request.method == "POST" and action == "notifications" else None, instance=request.user)

    if request.method == "POST" and action == "preferences":
        if section != "interface":
            return HttpResponseBadRequest("Настройки интерфейса отправлены не в тот раздел")
        if preferences_form.is_valid():
            preferences_form.save()
            request.session["django_language"] = request.user.language
            request.session["ui_theme"] = request.user.ui_theme
            audit(request, "preferences.updated", language=request.user.language, ui_theme=request.user.ui_theme)
            messages.success(request, _("Настройки интерфейса обновлены."))
            return redirect("accounts:interface_settings")

    if request.method == "POST" and action == "notifications":
        if section != "account":
            return HttpResponseBadRequest("Настройки уведомлений отправлены не в тот раздел")
        if notifications_form.is_valid():
            notifications_form.save()
            audit(request, "notifications.updated")
            messages.success(request, "Настройки уведомлений обновлены.")
            return redirect("accounts:settings")

    if request.method == "POST" and action == "auth_mode":
        if section != "account":
            return HttpResponseBadRequest("Настройки входа отправлены не в тот раздел")
        if form.is_valid():
            form.save()
            audit(request, "security.auth_mode_changed", mode=request.user.auth_mode)
            messages.success(request, _("Способ входа обновлён."))
            return redirect("accounts:settings")

    largest_files = []
    if section == "storage":
        largest_files = request.user.stored_files.select_related("folder").order_by("-size", "display_name")[:10]

    used = request.user.used_bytes
    reserved = request.user.reserved_bytes
    limit = request.user.quota_bytes
    return render(request, "accounts/settings.html", {
        "settings_section": section,
        "form": form,
        "preferences_form": preferences_form,
        "notifications_form": notifications_form,
        "largest_files": largest_files,
        "storage_used_mib": used / 1024 / 1024,
        "storage_reserved_mib": reserved / 1024 / 1024,
        "storage_free_mib": max(0, limit - used - reserved) / 1024 / 1024,
        "max_upload_mib": settings.MAX_SINGLE_UPLOAD_BYTES / 1024 / 1024,
        "upload_chunk_mib": settings.UPLOAD_CHUNK_BYTES / 1024 / 1024,
        "telegram_bot_configured": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_USERNAME),
    })


@login_required
@require_POST
def telegram_link_view(request):
    if not settings.TELEGRAM_ENABLED or not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_BOT_USERNAME:
        return JsonResponse({"error": "telegram_unavailable"}, status=503)
    from django.db import transaction
    from core.audit import allow_action
    if not allow_action("telegram_link", str(request.user.pk), limit=10, window_seconds=900):
        return JsonResponse({"error": "rate_limited"}, status=429)
    token = secrets.token_urlsafe(24)
    now = timezone.now()
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if user.telegram_user_id:
            return JsonResponse({"error": "telegram_already_linked"}, status=409)
        TelegramLinkAttempt.objects.filter(user=user, used_at__isnull=True).update(expires_at=now)
        attempt = TelegramLinkAttempt.objects.create(user=user, token_digest=TelegramLinkAttempt.digest_token(token), expires_at=now + timedelta(seconds=min(settings.TELEGRAM_LINK_TTL_SECONDS, 900)))
    audit(request, "telegram.link_started")
    return JsonResponse({"url": f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}", "expires_at": attempt.expires_at.isoformat()})


@login_required
@require_GET
def telegram_status_view(request):
    if not settings.TELEGRAM_ENABLED:
        return JsonResponse({"enabled": False, "linked": False})
    user = User.objects.only("telegram_user_id", "telegram_username", "telegram_first_name", "telegram_linked_at", "quota_bytes").get(pk=request.user.pk)
    return JsonResponse({
        "linked": bool(user.telegram_user_id),
        "telegram_user_id": str(user.telegram_user_id or ""),
        "linked_at": user.telegram_linked_at.isoformat() if user.telegram_linked_at else "",
        "display_name": user.telegram_display_name,
        "quota_bytes": user.quota_bytes,
    })


@csrf_exempt
@require_POST
def telegram_webhook_view(request):
    if not settings.TELEGRAM_ENABLED:
        return JsonResponse({"error": "telegram_disabled"}, status=410)
    configured_secret = settings.TELEGRAM_WEBHOOK_SECRET
    supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not configured_secret or not hmac.compare_digest(configured_secret, supplied_secret):
        return JsonResponse({"ok": False}, status=403)
    if len(request.body) > 1024 * 1024:
        return JsonResponse({"ok": False}, status=413)
    try:
        update = json.loads(request.body)
        handle_update(update)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"ok": False}, status=400)
    except TelegramAPIError:
        return JsonResponse({"ok": False}, status=502)
    return JsonResponse({"ok": True})


@login_required
def delete_account_view(request):
    form = DeleteAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        user = request.user
        user.scheduled_deletion_at = timezone.now() + timedelta(days=30)
        user.is_active = False
        user.save(update_fields=["scheduled_deletion_at", "is_active"])
        from sharing.models import ShareLink
        from django.db.models import F
        ShareLink.objects.filter(owner=user, active=True).update(active=False, revision=F("revision") + 1)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = signing.dumps(
            {"uid": user.pk, "scheduled": user.scheduled_deletion_at.isoformat()},
            salt="cloud-nimbus-account-recovery",
            compress=True,
        )
        recovery_url = request.build_absolute_uri(reverse("accounts:recover_account", args=[uid, token]))
        send_mail("Удаление аккаунта cloud.nimbus запланировано", f"Аккаунт будет удалён через 30 дней. Для отмены удаления откройте:\n{recovery_url}", None, [user.email])
        audit(request, "account.deletion_scheduled", actor=user)
        logout(request)
        messages.success(request, "Аккаунт заблокирован. В течение 30 дней его можно восстановить по ссылке из письма.")
        return redirect("accounts:login")
    return render(request, "accounts/delete_account.html", {"form": form})


def recover_account_view(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError):
        user = None
    payload = None
    try:
        payload = signing.loads(token, salt="cloud-nimbus-account-recovery", max_age=timedelta(days=30))
    except signing.BadSignature:
        pass
    valid = bool(
        user
        and payload
        and payload.get("uid") == user.pk
        and user.scheduled_deletion_at
        and payload.get("scheduled") == user.scheduled_deletion_at.isoformat()
        and user.scheduled_deletion_at > timezone.now()
    )
    if request.method == "POST" and valid:
        user.is_active = True
        user.scheduled_deletion_at = None
        user.save(update_fields=["is_active", "scheduled_deletion_at"])
        audit(request, "account.deletion_cancelled", actor=user)
        messages.success(request, "Аккаунт восстановлен. Теперь можно войти.")
        return redirect("accounts:login")
    return render(request, "accounts/recover_account.html", {"valid": valid})


class SafePasswordResetView(auth_views.PasswordResetView):
    form_class = VerifiedPasswordResetForm

    def post(self, request, *args, **kwargs):
        key = f"{client_ip(request)}:{request.POST.get('email', '').casefold()}"
        if not allow_action("password_reset", key, limit=3, window_seconds=3600):
            return redirect(self.get_success_url())
        audit(request, "password_reset.requested")
        return super().post(request, *args, **kwargs)


def logout_view(request):
    if request.method == "POST":
        audit(request, "logout")
        logout(request)
    return redirect("accounts:login")


def admin_login_redirect(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("admin:index")
        messages.error(request, "Для панели администрирования нужны права сотрудника.")
        return redirect("drive:home")
    return redirect(f"{reverse('accounts:login')}?next={reverse('admin:index')}")
