import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from accounts.models import OneTimeCode
from accounts.services import send_code
from core.audit import allow_action, audit, client_ip
from vaults.models import Vault
from vaults.validation import envelope, uuid_value

from .models import OpaqueChallenge, OpaqueCredential
from .protocol import OpaqueError, OpaqueUnavailable, call_opaque

User = get_user_model()
SERVER_IDENTIFIER = "cloud-cypher-v1"
SESSION_BINDING = "opaque_exchange_nonce"
RECENT_AUTH = "opaque_recent_auth"
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
_PROTOCOL_MESSAGE = re.compile(r"^[A-Za-z0-9_+/=-]+$")


def _error(code, status=400):
    return JsonResponse({"error": code}, status=status)


def opaque_endpoint(view):
    @wraps(view)
    @never_cache
    @require_POST
    def wrapped(request):
        if not settings.OPAQUE_ENABLED or settings.SESSION_ENGINE == "django.contrib.sessions.backends.signed_cookies":
            return _error("opaque_unavailable", 503)
        return view(request)
    return wrapped


def _body(request, required, optional=()):
    if request.content_type != "application/json" or len(request.body) > 16384:
        raise ValueError("invalid_request")
    try:
        payload = json.loads(request.body)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid_request") from exc
    if not isinstance(payload, dict) or not set(required).issubset(payload) or set(payload) - set(required) - set(optional):
        raise ValueError("invalid_request")
    return payload


def _username(value):
    if not isinstance(value, str):
        raise ValueError("invalid_username")
    value = value.strip().lower()
    if not _USERNAME.fullmatch(value):
        raise ValueError("invalid_username")
    return value


def _message(value):
    if not isinstance(value, str) or not 16 <= len(value) <= 8192 or not _PROTOCOL_MESSAGE.fullmatch(value):
        raise ValueError("invalid_message")
    return value


def _identifiers(username):
    return {"client": username, "server": SERVER_IDENTIFIER}


def _login_identity(value):
    if not isinstance(value, str):
        raise ValueError("invalid_identifier")
    value = value.strip().lower()
    if "@" in value:
        if len(value) > 254:
            raise ValueError("invalid_identifier")
        validate_email(value)
        user = User.objects.filter(email__iexact=value).first()
        # OPAQUE's fake-record path must also have a stable, valid identifier.
        username = user.username if user else "user-" + hashlib.sha256(value.encode()).hexdigest()[:32]
        return value, username, user
    username = _username(value)
    return value, username, User.objects.filter(username=username).first()


def _rate(request, action, identifier):
    ip_ok = allow_action(f"opaque_{action}_ip", client_ip(request), limit=30, window_seconds=900)
    name_ok = allow_action(f"opaque_{action}_name", identifier, limit=10, window_seconds=900)
    if not ip_ok or not name_ok:
        audit(request, "opaque.rate_limited", success=False, reason=action)
        return False
    return True


def _session_digest(request, *, create=False):
    nonce = request.session.get(SESSION_BINDING)
    if not isinstance(nonce, str):
        if not create:
            return None
        nonce = secrets.token_urlsafe(32)
        request.session[SESSION_BINDING] = nonce
    return hashlib.sha256(nonce.encode()).hexdigest()


def _issue(request, kind, payload, user=None):
    return OpaqueChallenge.objects.create(
        kind=kind,
        user=user,
        payload=payload,
        session_digest=_session_digest(request, create=True),
        expires_at=timezone.now() + timedelta(seconds=120),
    )


@sensitive_variables()
def _consume(request, challenge_id, kind):
    try:
        identifier = uuid.UUID(str(challenge_id))
    except (ValueError, TypeError, AttributeError):
        return None
    binding = _session_digest(request)
    if binding is None:
        return None
    with transaction.atomic():
        challenge = OpaqueChallenge.objects.select_for_update().filter(pk=identifier, kind=kind).first()
        if challenge is None or challenge.consumed_at or not hmac.compare_digest(challenge.session_digest, binding):
            return None
        payload = dict(challenge.payload)
        valid = challenge.expires_at > timezone.now()
        challenge.consumed_at = timezone.now()
        challenge.payload = {}
        challenge.save(update_fields=["consumed_at", "payload"])
        return (payload, challenge.user_id) if valid else None


def _available(user):
    return user is not None and user.is_authenticated and user.is_active and user.email_verified and user.scheduled_deletion_at is None


def _recent(request, user, version):
    marker = request.session.get(RECENT_AUTH)
    if isinstance(marker, dict) and marker.get("credential_version") == version and _fresh_marker(marker, user):
        return True
    if _fresh_marker(request.session.get("passkey_recent_auth"), user):
        return True
    return _fresh_marker(request.session.get("passkey_recent_reset"), user) and not Vault.objects.filter(owner=user, revoked_at__isnull=True).exists()


def _fresh_marker(marker, user):
    if not isinstance(marker, dict) or marker.get("user_id") != user.pk:
        return False
    timestamp = marker.get("authenticated_at")
    if type(timestamp) not in (int, float):
        return False
    return 0 <= timezone.now().timestamp() - timestamp < 300


def _mark_recent(request, user, version):
    request.session[RECENT_AUTH] = {"user_id": user.pk, "credential_version": version, "authenticated_at": timezone.now().timestamp()}


@opaque_endpoint
@sensitive_variables()
def register_start(request):
    try:
        payload = _body(request, {"username", "email", "registrationRequest"})
        username = _username(payload["username"])
        if not isinstance(payload["email"], str):
            raise ValueError("invalid_email")
        email = User.objects.normalize_email(payload["email"].strip()).lower()
        validate_email(email)
        if len(email) > 254:
            raise ValueError("invalid_email")
        registration_request = _message(payload["registrationRequest"])
    except (ValueError, TypeError, ValidationError):
        return _error("invalid_request")
    if not _rate(request, "register_start", username):
        return _error("rate_limited", 429)
    if User.objects.filter(username__iexact=username).exists() or User.objects.filter(email__iexact=email).exists():
        return _error("account_unavailable", 409)
    try:
        result = call_opaque("createRegistrationResponse", userIdentifier=username, registrationRequest=registration_request)
    except OpaqueUnavailable:
        return _error("opaque_unavailable", 503)
    except OpaqueError:
        return _error("invalid_request")
    challenge = _issue(request, OpaqueChallenge.Kind.REGISTER, {"username": username, "email": email})
    return JsonResponse({"challenge": str(challenge.pk), "username": username, "registrationResponse": result["registrationResponse"]})


@opaque_endpoint
@sensitive_variables()
def register_finish(request):
    try:
        body = _body(request, {"challenge", "registrationRecord"})
    except (ValueError, TypeError):
        return _error("invalid_request")
    consumed = _consume(request, body["challenge"], OpaqueChallenge.Kind.REGISTER)
    if consumed is None:
        return _error("authentication_failed", 401)
    payload, _ = consumed
    username, email = payload["username"], payload["email"]
    if not _rate(request, "register_finish", username):
        return _error("rate_limited", 429)
    try:
        record = _message(body["registrationRecord"])
        call_opaque("validateRegistrationRecord", userIdentifier=username, registrationRecord=record, identifiers=_identifiers(username))
    except OpaqueUnavailable:
        return _error("opaque_unavailable", 503)
    except (ValueError, OpaqueError):
        return _error("invalid_request")
    try:
        with transaction.atomic():
            if User.objects.filter(username__iexact=username).exists() or User.objects.filter(email__iexact=email).exists():
                return _error("account_unavailable", 409)
            user = User.objects.create_user(username=username, email=email, password=None, is_active=False, email_verified=False, auth_mode=User.AuthMode.PASSWORD)
            OpaqueCredential.objects.create(user=user, registration_record=record)
    except IntegrityError:
        return _error("account_unavailable", 409)
    request.session["verify_user_id"] = user.pk
    try:
        send_code(user, OneTimeCode.Purpose.VERIFY_EMAIL)
    except Exception:
        audit(request, "opaque.verification_email_failed", success=False, actor=user)
        return _error("verification_email_failed", 503)
    audit(request, "opaque.registration_started", actor=user)
    return JsonResponse({"verification_required": True, "verify_url": "/auth/verify-email/"})


@opaque_endpoint
@sensitive_variables()
def login_start(request):
    try:
        payload = _body(request, {"username", "startLoginRequest"})
        identifier, username, account = _login_identity(payload["username"])
        start_request = _message(payload["startLoginRequest"])
    except (ValueError, TypeError, ValidationError):
        return _error("invalid_request")
    if not _rate(request, "login_start", identifier):
        return _error("rate_limited", 429)
    credential = OpaqueCredential.objects.select_related("user").filter(user=account).first() if _available(account) else None
    try:
        result = call_opaque(
            "startLogin",
            userIdentifier=username,
            registrationRecord=credential.registration_record if credential else None,
            startLoginRequest=start_request,
            identifiers=_identifiers(username),
        )
    except OpaqueUnavailable:
        return _error("opaque_unavailable", 503)
    except OpaqueError:
        return _error("authentication_failed", 401)
    challenge = _issue(request, OpaqueChallenge.Kind.LOGIN, {
        "username": username,
        "credential_id": credential.pk if credential else None,
        "credential_version": credential.version if credential else 0,
        "auth_hash": credential.user.get_session_auth_hash() if credential else "",
        "server_login_state": result["serverLoginState"],
    }, user=credential.user if credential else None)
    return JsonResponse({"challenge": str(challenge.pk), "username": username, "loginResponse": result["loginResponse"]})


@opaque_endpoint
@sensitive_variables()
def login_finish(request):
    try:
        body = _body(request, {"challenge", "finishLoginRequest"})
    except (ValueError, TypeError):
        return _error("authentication_failed", 401)
    consumed = _consume(request, body["challenge"], OpaqueChallenge.Kind.LOGIN)
    if consumed is None:
        return _error("authentication_failed", 401)
    payload, user_id = consumed
    if not _rate(request, "login_finish", payload["username"]):
        return _error("rate_limited", 429)
    try:
        finish_request = _message(body["finishLoginRequest"])
        result = call_opaque("finishLogin", serverLoginState=payload["server_login_state"], finishLoginRequest=finish_request, identifiers=_identifiers(payload["username"]))
        if result.get("authenticated") is not True:
            raise OpaqueError("Invalid proof")
    except OpaqueUnavailable:
        return _error("opaque_unavailable", 503)
    except (ValueError, OpaqueError):
        audit(request, "opaque.login_failed", success=False)
        return _error("authentication_failed", 401)
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id).first()
        credential = OpaqueCredential.objects.select_for_update().filter(user_id=user_id).first()
        if (
            not _available(user)
            or credential is None
            or credential.pk != payload["credential_id"]
            or credential.version != payload["credential_version"]
            or not hmac.compare_digest(user.get_session_auth_hash(), payload["auth_hash"])
        ):
            return _error("authentication_failed", 401)
        if getattr(settings, "LOGIN_SECOND_FACTOR_REQUIRED", True):
            from otp_auth.services import OTPRateLimited, OTPUnavailable, begin_login

            try:
                pending_login = begin_login(request, user, credential)
            except OTPUnavailable:
                return _error("second_factor_unavailable", 503)
            except OTPRateLimited:
                return _error("rate_limited", 429)
            return JsonResponse(pending_login)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        _mark_recent(request, user, credential.version)
    audit(request, "opaque.login", actor=user)
    return JsonResponse({"ok": True})


@opaque_endpoint
@sensitive_variables()
def change_start(request):
    if not _available(request.user):
        return _error("authentication_failed", 401)
    credential = OpaqueCredential.objects.filter(user=request.user).first()
    version = credential.version if credential else 0
    if not _recent(request, request.user, version):
        return _error("recent_authentication_required", 403)
    try:
        body = _body(request, {"registrationRequest"})
        registration_request = _message(body["registrationRequest"])
    except (ValueError, TypeError):
        return _error("invalid_request")
    if not _rate(request, "change_start", request.user.username):
        return _error("rate_limited", 429)
    try:
        result = call_opaque("createRegistrationResponse", userIdentifier=request.user.username, registrationRequest=registration_request)
    except OpaqueUnavailable:
        return _error("opaque_unavailable", 503)
    except OpaqueError:
        return _error("invalid_request")
    vault_id = Vault.objects.filter(owner=request.user, revoked_at__isnull=True).values_list("pk", flat=True).first()
    challenge = _issue(request, OpaqueChallenge.Kind.CHANGE, {"username": request.user.username, "credential_version": version, "vault_id": str(vault_id) if vault_id else None}, user=request.user)
    return JsonResponse({"challenge": str(challenge.pk), "username": request.user.username, "registrationResponse": result["registrationResponse"]})


@opaque_endpoint
@sensitive_variables()
def change_finish(request):
    if not _available(request.user):
        return _error("authentication_failed", 401)
    try:
        body = _body(request, {"challenge", "registrationRecord"}, {"vault_id", "wrapped_key"})
    except (ValueError, TypeError):
        return _error("invalid_request")
    consumed = _consume(request, body["challenge"], OpaqueChallenge.Kind.CHANGE)
    if consumed is None:
        return _error("authentication_failed", 401)
    payload, user_id = consumed
    if user_id != request.user.pk:
        return _error("authentication_failed", 401)
    if not _rate(request, "change_finish", request.user.username):
        return _error("rate_limited", 429)
    try:
        record = _message(body["registrationRecord"])
        if payload["vault_id"]:
            if "wrapped_key" not in body or "vault_id" not in body:
                return _error("vault_rewrap_required")
            new_wrapper = envelope(body["wrapped_key"], wrapped_key=True)
            if str(uuid_value(body["vault_id"])) != payload["vault_id"]:
                return _error("vault_changed", 409)
        elif "wrapped_key" in body or "vault_id" in body:
            return _error("vault_changed", 409)
        call_opaque("validateRegistrationRecord", userIdentifier=payload["username"], registrationRecord=record, identifiers=_identifiers(payload["username"]))
    except OpaqueUnavailable:
        return _error("opaque_unavailable", 503)
    except (ValueError, OpaqueError):
        return _error("invalid_request")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        credential = OpaqueCredential.objects.select_for_update().filter(user=user).first()
        vault = Vault.objects.select_for_update().filter(owner=user, revoked_at__isnull=True).first()
        version = credential.version if credential else 0
        if not _available(user) or version != payload["credential_version"]:
            return _error("authentication_failed", 401)
        if not _recent(request, user, version):
            return _error("recent_authentication_required", 403)
        if (str(vault.pk) if vault else None) != payload["vault_id"]:
            return _error("vault_changed", 409)
        if vault:
            vault.wrapped_key = new_wrapper
            vault.save(update_fields=["wrapped_key"])
        if credential is None:
            credential = OpaqueCredential.objects.create(user=user, registration_record=record)
        else:
            credential.registration_record = record
            credential.version += 1
            credential.save(update_fields=["registration_record", "version", "updated_at"])
        # A fresh unusable password randomizes Django's session auth hash without
        # receiving a password. Only the current session gets the updated hash.
        user.set_unusable_password()
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)
        _mark_recent(request, user, credential.version)
    audit(request, "opaque.password_changed", actor=user)
    return JsonResponse({"ok": True})
