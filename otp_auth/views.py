import hmac
import json
import re
import uuid
from datetime import timedelta
from functools import wraps

import pyotp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from core.audit import audit
from opaque_auth.models import OpaqueCredential

from .models import OtpChallenge, TotpCredential
from .services import matching_counter, rate, session_digest

User = get_user_model()


def _error(code="authentication_failed", status=401):
    return JsonResponse({"error": code}, status=status)


def endpoint(view):
    @wraps(view)
    @never_cache
    @require_POST
    @sensitive_variables()
    def wrapped(request):
        if settings.SESSION_ENGINE == "django.contrib.sessions.backends.signed_cookies":
            return _error("second_factor_unavailable", 503)
        try:
            return view(request)
        except (ValueError, TypeError, KeyError):
            return _error()
    return wrapped


def _body(request, required):
    if request.content_type != "application/json" or len(request.body) > 2048:
        raise ValueError("invalid_request")
    try:
        payload = json.loads(request.body)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid_request") from exc
    if not isinstance(payload, dict) or set(payload) != set(required):
        raise ValueError("invalid_request")
    return payload


def _available(user):
    return user is not None and user.is_authenticated and user.is_active and user.scheduled_deletion_at is None


def _enrollable(user):
    from accounts.onboarding import state
    if not _available(user):
        return False
    gates = state(user)
    return gates['telegram_ready'] and (gates['passkey_ready'] or gates['passkey_skipped'])


def _recent(request, user):
    for name in ("opaque_recent_auth", "passkey_recent_auth"):
        marker = request.session.get(name)
        if not isinstance(marker, dict) or marker.get("user_id") != user.pk:
            continue
        timestamp = marker.get("authenticated_at")
        if type(timestamp) not in (int, float) or not 0 <= timezone.now().timestamp() - timestamp < 300:
            continue
        if name == "opaque_recent_auth" and not OpaqueCredential.objects.filter(user=user, version=marker.get("credential_version")).exists():
            continue
        return True
    return False


def _usable(challenge, binding):
    return challenge is not None and binding is not None and challenge.consumed_at is None and challenge.attempts < 5 and challenge.expires_at > timezone.now() and hmac.compare_digest(challenge.session_digest, binding)


def _attempt(challenge, successful):
    challenge.attempts += 1
    if successful or challenge.attempts >= 5:
        challenge.consumed_at = timezone.now()
        challenge.payload = {}
    challenge.save(update_fields=["attempts", "consumed_at", "payload"])


def _parse_proof(request):
    payload = _body(request, {"challenge", "code"})
    if not isinstance(payload["code"], str) or not re.fullmatch(r"[0-9]{6}", payload["code"]):
        raise ValueError("invalid_code")
    return uuid.UUID(str(payload["challenge"])), payload["code"]


@endpoint
@sensitive_variables()
def setup_start(request):
    _body(request, set())
    if not _enrollable(request.user) or not _recent(request, request.user):
        return _error()
    if not rate(request, "setup", request.user.pk, limit=5):
        return _error("rate_limited", 429)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not _enrollable(user) or not _recent(request, user):
            return _error()
        if TotpCredential.objects.filter(user=user).exists():
            return _error("totp_already_enabled", 409)
        OtpChallenge.objects.filter(user=user, kind="setup", consumed_at__isnull=True).update(consumed_at=timezone.now(), payload={})
        secret = pyotp.random_base32()
        challenge = OtpChallenge.objects.create(user=user, kind="setup", method="totp", session_digest=session_digest(request, create=True), payload={"secret": secret, "auth_hash": user.get_session_auth_hash()}, expires_at=timezone.now() + timedelta(minutes=5))
    return JsonResponse({"challenge": str(challenge.pk), "secret": secret, "otpauth_uri": pyotp.TOTP(secret, digits=6, interval=30).provisioning_uri(name=user.username, issuer_name="cloud.nimbus")})


@endpoint
@sensitive_variables()
def setup_finish(request):
    identifier, code = _parse_proof(request)
    if not _enrollable(request.user) or not _recent(request, request.user):
        return _error()
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        challenge = OtpChallenge.objects.select_for_update().filter(pk=identifier, user=user, kind="setup").first()
        if not _enrollable(user) or not _recent(request, user) or not _usable(challenge, session_digest(request)) or not hmac.compare_digest(challenge.payload["auth_hash"], user.get_session_auth_hash()):
            return _error()
        if TotpCredential.objects.filter(user=user).exists():
            return _error("totp_already_enabled", 409)
        secret = challenge.payload["secret"]
        counter = matching_counter(secret, code)
        _attempt(challenge, counter is not None)
        if counter is None:
            return _error()
        TotpCredential.objects.create(user=user, secret=secret, last_counter=counter)
        # Email challenges issued before enrollment must not bypass this factor.
        OtpChallenge.objects.filter(user=user, kind="login", consumed_at__isnull=True).update(consumed_at=timezone.now(), payload={})
    request.session["nimbus_access"] = user.pk
    audit(request, "otp.totp_enabled", actor=user)
    return JsonResponse({"ok": True})


@endpoint
@sensitive_variables()
def login_finish(request):
    identifier, code = _parse_proof(request)
    candidate = OtpChallenge.objects.filter(pk=identifier, kind="login").first()
    if candidate is None or not rate(request, "login_finish", candidate.user_id, limit=30):
        return _error()
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=candidate.user_id)
        challenge = OtpChallenge.objects.select_for_update().get(pk=identifier)
        if not _available(user) or not _usable(challenge, session_digest(request)):
            return _error()
        payload = challenge.payload
        credential = OpaqueCredential.objects.select_for_update().filter(user=user).first()
        if credential is None or credential.pk != payload["credential_id"] or credential.version != payload["credential_version"] or not hmac.compare_digest(payload["auth_hash"], user.get_session_auth_hash()):
            return _error()
        totp = TotpCredential.objects.select_for_update().filter(user=user).first()
        counter = None
        if challenge.method == "totp":
            if totp is None or totp.pk != payload["totp_id"]:
                return _error()
            counter = matching_counter(totp.secret, code, after=totp.last_counter)
            successful = counter is not None
        else:
            return _error()
        _attempt(challenge, successful)
        if not successful:
            return _error()
        if totp is not None:
            totp.last_counter = counter
            totp.save(update_fields=["last_counter"])
        from accounts.onboarding import begin
        begin(request, user, full=True)
        request.session["opaque_recent_auth"] = {"user_id": user.pk, "credential_version": credential.version, "authenticated_at": timezone.now().timestamp()}
    audit(request, "opaque.login_with_otp", actor=user, mode=challenge.method)
    return JsonResponse({"username": user.username})
