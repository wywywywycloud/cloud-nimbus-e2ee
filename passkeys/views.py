import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST
from webauthn import generate_authentication_options, generate_registration_options, verify_authentication_response, verify_registration_response
from webauthn.helpers import options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, CredentialDeviceType, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement

from core.audit import allow_action, audit, client_ip
from opaque_auth.models import OpaqueChallenge, OpaqueCredential
from vaults.models import CipherFile, CipherFolder, Vault
from vaults.validation import envelope, uuid_value

from .models import PasskeyChallenge, PasskeyCredential, PasskeyIdentity, PasskeyReset

User = get_user_model()
PRF_SALT = hashlib.sha256(b"cloud-cypher:passkey-prf:v1").digest()
SESSION_BINDING = "passkey_exchange_nonce"


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid_encoding")
    result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(result) != value:
        raise ValueError("invalid_encoding")
    return result


def _error(code="authentication_failed", status=401):
    return JsonResponse({"error": code}, status=status)


def endpoint(view):
    @wraps(view)
    @never_cache
    @require_POST
    @sensitive_variables()
    def wrapped(request):
        if not settings.PASSKEY_RP_ID or not settings.PASSKEY_ORIGIN or settings.SESSION_ENGINE == "django.contrib.sessions.backends.signed_cookies":
            return _error("passkeys_unavailable", 503)
        try:
            return view(request)
        except (ValueError, TypeError, KeyError, RecursionError, ObjectDoesNotExist, ValidationError, WebAuthnException):
            return _error()
    return wrapped


def _body(request, required, optional=()):
    if request.content_type != "application/json" or len(request.body) > 24 * 1024:
        raise ValueError("invalid_request")
    try:
        result = json.loads(request.body)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid_request") from exc
    if not isinstance(result, dict) or not set(required).issubset(result) or set(result) - set(required) - set(optional):
        raise ValueError("invalid_request")
    return result


def _available(user):
    return user is not None and user.is_authenticated and user.is_active and user.scheduled_deletion_at is None


def _recent(request, user):
    for name in ("opaque_recent_auth", "passkey_recent_auth", "passkey_recent_reset"):
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


def _session_digest(request, *, create=False):
    nonce = request.session.get(SESSION_BINDING)
    if not isinstance(nonce, str):
        if not create:
            return None
        nonce = secrets.token_urlsafe(32)
        request.session[SESSION_BINDING] = nonce
    return hashlib.sha256(nonce.encode()).hexdigest()


def _rate(request, action, key, *, limit=15):
    return allow_action(f"passkey_{action}_ip", client_ip(request), limit=60, window_seconds=900) and allow_action(f"passkey_{action}_account", key, limit=limit, window_seconds=900)


def _issue(request, kind, *, user=None, credential=None):
    raw = secrets.token_bytes(32)
    payload = {"challenge": _b64(raw)}
    if user:
        payload["auth_hash"] = user.get_session_auth_hash()
    if credential:
        payload["credential_id"] = credential.credential_id
    challenge = PasskeyChallenge.objects.create(kind=kind, user=user, session_digest=_session_digest(request, create=True), payload=payload, expires_at=timezone.now() + timedelta(seconds=120))
    return challenge, raw


def _consume(request, identifier, kind):
    identifier = uuid.UUID(str(identifier))
    binding = _session_digest(request)
    if binding is None:
        return None
    with transaction.atomic():
        challenge = PasskeyChallenge.objects.select_for_update().filter(pk=identifier, kind=kind).first()
        if challenge is None or challenge.consumed_at or not hmac.compare_digest(challenge.session_digest, binding):
            return None
        payload = dict(challenge.payload)
        valid = challenge.expires_at > timezone.now()
        challenge.consumed_at = timezone.now()
        challenge.payload = {}
        challenge.save(update_fields=["consumed_at", "payload"])
        return (payload, challenge.user_id) if valid else None


def _credential(value, *, registration=False):
    # Never accept the PRF secret returned by credential.toJSON(). Only the
    # signature/public registration response belongs on the server.
    if not isinstance(value, dict) or set(value) - {"id", "rawId", "type", "response", "authenticatorAttachment", "clientExtensionResults"}:
        raise ValueError("invalid_credential")
    if value.get("type") != "public-key" or value.get("id") != value.get("rawId"):
        raise ValueError("invalid_credential")
    identifier = _unb64(value["id"])
    if not 16 <= len(identifier) <= 1024:
        raise ValueError("invalid_credential")
    extensions = value.get("clientExtensionResults", {})
    if not isinstance(extensions, dict) or set(extensions) - {"prf"}:
        raise ValueError("invalid_extensions")
    if "prf" in extensions:
        prf = extensions["prf"]
        if not isinstance(prf, dict) or set(prf) - {"enabled"} or ("enabled" in prf and type(prf["enabled"]) is not bool):
            raise ValueError("secret_extension_forbidden")
    response = value.get("response")
    required = {"clientDataJSON", "attestationObject"} if registration else {"clientDataJSON", "authenticatorData", "signature"}
    optional = {"transports"} if registration else {"userHandle"}
    if not isinstance(response, dict) or not required.issubset(response) or set(response) - required - optional:
        raise ValueError("invalid_response")
    for name in required:
        _unb64(response[name])
    if response.get("userHandle") is not None:
        _unb64(response["userHandle"])
    # Reject embedded contexts even if a browser later supports cross-origin
    # WebAuthn; this application intentionally has one exact trusted origin.
    client_data = json.loads(_unb64(response["clientDataJSON"]))
    if not isinstance(client_data, dict) or client_data.get("crossOrigin", False) is not False or "topOrigin" in client_data:
        raise ValueError("embedded_context_forbidden")
    return {key: item for key, item in value.items() if key != "clientExtensionResults"}


def _options(challenge, options):
    public_key = json.loads(options_to_json(options))
    public_key["extensions"] = {"prf": {"eval": {"first": _b64(PRF_SALT)}}}
    return JsonResponse({"challenge": str(challenge.pk), "publicKey": public_key})


def _auth_options(raw, credential=None):
    return generate_authentication_options(rp_id=settings.PASSKEY_RP_ID, challenge=raw, timeout=120000, user_verification=UserVerificationRequirement.REQUIRED, allow_credentials=[PublicKeyCredentialDescriptor(id=_unb64(credential.credential_id))] if credential else None)


def _verify_assertion(credential, response, payload, user):
    user_handle = response["response"].get("userHandle")
    if user_handle is not None and not hmac.compare_digest(_unb64(user_handle), bytes(user.passkey_identity.user_handle)):
        raise ValueError("invalid_user_handle")
    result = verify_authentication_response(credential=response, expected_challenge=_unb64(payload["challenge"]), expected_rp_id=settings.PASSKEY_RP_ID, expected_origin=settings.PASSKEY_ORIGIN, credential_public_key=bytes(credential.public_key), credential_current_sign_count=credential.sign_count, require_user_verification=True)
    if result.credential_device_type != CredentialDeviceType.MULTI_DEVICE or not credential.backup_eligible:
        raise ValueError("backup_eligibility_changed")
    credential.sign_count = result.new_sign_count
    credential.backed_up = result.credential_backed_up
    credential.last_used_at = timezone.now()
    credential.save(update_fields=["sign_count", "backed_up", "last_used_at"])


@endpoint
def register_start(request):
    _body(request, set())
    if (not _available(request.user) or not request.user.telegram_user_id) or not _recent(request, request.user):
        return _error()
    if not _rate(request, "register", str(request.user.pk)):
        return _error("rate_limited", 429)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if (not _available(user) or not user.telegram_user_id) or not _recent(request, user):
            return _error()
        if PasskeyCredential.objects.filter(user=user, active=True).exists():
            return _error("credential_already_exists", 409)
        identity, _ = PasskeyIdentity.objects.get_or_create(user=user)
        challenge, raw = _issue(request, "register", user=user)
    options = generate_registration_options(rp_id=settings.PASSKEY_RP_ID, rp_name="cloud.nimbus", user_id=bytes(identity.user_handle), user_name=user.username, user_display_name=user.username, challenge=raw, timeout=120000, authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, require_resident_key=True, user_verification=UserVerificationRequirement.REQUIRED))
    return _options(challenge, options)


@endpoint
def register_finish(request):
    body = _body(request, {"challenge", "credential"})
    consumed = _consume(request, body["challenge"], "register")
    if consumed is None or (not _available(request.user) or not request.user.telegram_user_id) or consumed[1] != request.user.pk:
        return _error()
    payload, _ = consumed
    response = _credential(body["credential"], registration=True)
    result = verify_registration_response(credential=response, expected_challenge=_unb64(payload["challenge"]), expected_rp_id=settings.PASSKEY_RP_ID, expected_origin=settings.PASSKEY_ORIGIN, require_user_presence=True, require_user_verification=True)
    if result.credential_device_type != CredentialDeviceType.MULTI_DEVICE:
        return _error("synced_passkey_required", 400)
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if (not _available(user) or not user.telegram_user_id) or not _recent(request, user) or not hmac.compare_digest(payload["auth_hash"], user.get_session_auth_hash()):
                return _error()
            if PasskeyCredential.objects.filter(user=user, active=True).exists():
                return _error("credential_already_exists", 409)
            PasskeyCredential.objects.filter(user=user, active=False).delete()
            credential = PasskeyCredential.objects.create(user=user, credential_id=_b64(result.credential_id), public_key=result.credential_public_key, sign_count=result.sign_count, backup_eligible=True, backed_up=result.credential_backed_up)
    except IntegrityError:
        return _error()
    return JsonResponse({"id": credential.credential_id}, status=201)


@endpoint
def activate_start(request):
    body = _body(request, {"credential_id"})
    if (not _available(request.user) or not request.user.telegram_user_id) or not _recent(request, request.user):
        return _error()
    credential = PasskeyCredential.objects.filter(user=request.user, credential_id=body["credential_id"], active=False).first()
    if credential is None or credential.created_at < timezone.now() - timedelta(minutes=5):
        return _error()
    challenge, raw = _issue(request, "activate", user=request.user, credential=credential)
    return _options(challenge, _auth_options(raw, credential))


@endpoint
def activate_finish(request):
    body = _body(request, {"challenge", "credential", "vault_id", "wrapped_key"})
    consumed = _consume(request, body["challenge"], "activate")
    if consumed is None or (not _available(request.user) or not request.user.telegram_user_id) or consumed[1] != request.user.pk:
        return _error()
    payload, _ = consumed
    response = _credential(body["credential"])
    vault_id = uuid_value(body["vault_id"])
    wrapped_key = envelope(body["wrapped_key"], wrapped_key=True)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if (not _available(user) or not user.telegram_user_id) or not _recent(request, user) or not hmac.compare_digest(payload["auth_hash"], user.get_session_auth_hash()):
            return _error()
        vault = Vault.objects.select_for_update().filter(pk=vault_id, owner=user, revoked_at__isnull=True).first()
        credential = PasskeyCredential.objects.select_for_update().filter(user=user, credential_id=payload["credential_id"], active=False).first()
        if vault is None or credential is None or response["id"] != credential.credential_id or PasskeyCredential.objects.filter(user=user, active=True).exists():
            return _error()
        _verify_assertion(credential, response, payload, user)
        if not credential.backed_up:
            return _error("passkey_backup_required", 400)
        credential.active = True
        credential.vault = vault
        credential.wrapped_key = wrapped_key
        credential.save(update_fields=["active", "vault", "wrapped_key"])
    request.session["passkey_recent_auth"] = {"user_id": user.pk, "authenticated_at": timezone.now().timestamp()}
    request.session.pop("passkey_recent_reset", None)
    from accounts.onboarding import state
    if not state(user)["onboarding_required"]:
        request.session["nimbus_access"] = user.pk
    audit(request, "passkey.activated", actor=user)
    return JsonResponse({"ok": True})


@endpoint
def login_start(request):
    body = _body(request, set(), {"username"})
    username = body.get("username", "")
    if not isinstance(username, str) or len(username) > 254:
        raise ValueError("invalid_username")
    username = username.strip().lower()
    if username:
        from opaque_auth.views import _username
        username = _username(username)
    if not _rate(request, "login", username or "discoverable", limit=30):
        return _error("rate_limited", 429)
    user = User.objects.filter(username=username, is_active=True, scheduled_deletion_at__isnull=True).first() if username else None
    credential = PasskeyCredential.objects.filter(user=user, active=True, vault__revoked_at__isnull=True).first() if user else None
    challenge, raw = _issue(request, "login", user=user, credential=credential)
    if username and credential is None:
        # Match the shape of an existing username without revealing credential IDs.
        unavailable_id = secrets.token_bytes(32)
        challenge.payload["credential_id"] = _b64(unavailable_id)
        challenge.save(update_fields=["payload"])
        options = generate_authentication_options(rp_id=settings.PASSKEY_RP_ID, challenge=raw, timeout=120000, user_verification=UserVerificationRequirement.REQUIRED, allow_credentials=[PublicKeyCredentialDescriptor(id=unavailable_id)])
    else:
        options = _auth_options(raw, credential)
    return _options(challenge, options)


@endpoint
def login_finish(request):
    body = _body(request, {"challenge", "credential"})
    consumed = _consume(request, body["challenge"], "login")
    if consumed is None:
        return _error()
    payload, expected_user = consumed
    response = _credential(body["credential"])
    if expected_user is None and response["response"].get("userHandle") is None:
        return _error()
    candidate = PasskeyCredential.objects.filter(credential_id=response["id"], active=True).first()
    if candidate is None or (expected_user is not None and candidate.user_id != expected_user) or (payload.get("credential_id") is not None and candidate.credential_id != payload["credential_id"]):
        return _error()
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=candidate.user_id)
        # Lock concrete rows in the same user -> vault -> credential order as activation.
        # A nullable vault FK must never introduce an outer join into FOR UPDATE.
        vault = Vault.objects.select_for_update().filter(pk=candidate.vault_id, owner=user, revoked_at__isnull=True).first()
        credential = PasskeyCredential.objects.select_for_update().filter(pk=candidate.pk, user=user, active=True, vault_id=candidate.vault_id).first()
        if not _available(user) or vault is None or credential is None:
            return _error()
        if expected_user is not None and not hmac.compare_digest(payload["auth_hash"], user.get_session_auth_hash()):
            return _error()
        _verify_assertion(credential, response, payload, user)
        vault_data = {"id": str(credential.vault_id), "version": vault.version, "wrapped_key": credential.wrapped_key}
        from accounts.onboarding import begin
        begin(request, user, full=True)
        request.session["passkey_recent_auth"] = {"user_id": user.pk, "authenticated_at": timezone.now().timestamp()}
    audit(request, "passkey.login", actor=user)
    return JsonResponse({"username": user.username, "vault": vault_data})


def _code_digest(identifier, code):
    return hmac.new(settings.SECRET_KEY.encode(), f"passkey-reset:{identifier}:{code}".encode(), hashlib.sha256).hexdigest()


@endpoint
@sensitive_variables()
def reset_start(request):
    body = _body(request, {"username"})
    if not isinstance(body["username"], str) or len(body["username"]) > 254:
        raise ValueError("invalid_username")
    username = body["username"].strip().lower()
    from opaque_auth.views import _username
    username = _username(username)
    if not _rate(request, "reset", username, limit=5):
        return _error("rate_limited", 429)
    user = User.objects.filter(username=username, is_active=True, scheduled_deletion_at__isnull=True).first()
    code = f"{secrets.randbelow(1000000):06d}"
    identifier = uuid.uuid4()
    challenge = PasskeyReset.objects.create(id=identifier, user=user, session_digest=_session_digest(request, create=True), code_digest=_code_digest(identifier, code), auth_hash=user.get_session_auth_hash() if user else "", telegram_user_id=user.telegram_user_id if user else None, expires_at=timezone.now() + timedelta(minutes=10))
    if user and user.telegram_user_id:
        try:
            from accounts.telegram import send_message
            send_message(user.telegram_user_id, f"cloud.nimbus: сброс passkey полностью удалит файлы. Код: {code}. Действует 10 минут. Если вы не запрашивали сброс, не сообщайте код.")
        except Exception:
            # Keep the same public response for unknown usernames and Telegram delivery errors.
            audit(request, "passkey.reset_telegram_failed", success=False, actor=user)
    return JsonResponse({"challenge": str(challenge.pk)})


@endpoint
@sensitive_variables()
def reset_finish(request):
    from otp_auth.models import OtpChallenge, TotpCredential

    body = _body(request, {"challenge", "code", "confirmation"})
    if body["confirmation"] != "DELETE ALL FILES" or not isinstance(body["code"], str) or not re.fullmatch(r"[0-9]{6}", body["code"]):
        return _error()
    identifier = uuid.UUID(str(body["challenge"]))
    binding = _session_digest(request)
    if binding is None:
        return _error()
    candidate = PasskeyReset.objects.filter(pk=identifier).first()
    if candidate is None or candidate.user_id is None:
        return _error()
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=candidate.user_id)
        challenge = PasskeyReset.objects.select_for_update().get(pk=identifier)
        if challenge.consumed_at or challenge.attempts >= 5 or challenge.expires_at <= timezone.now() or not hmac.compare_digest(challenge.session_digest, binding) or not _available(user) or not user.telegram_user_id or user.telegram_user_id != challenge.telegram_user_id or not hmac.compare_digest(challenge.auth_hash, user.get_session_auth_hash()):
            return _error()
        challenge.attempts += 1
        matches = hmac.compare_digest(challenge.code_digest, _code_digest(identifier, body["code"]))
        if matches or challenge.attempts >= 5:
            challenge.consumed_at = timezone.now()
            challenge.code_digest = ""
        challenge.save(update_fields=["attempts", "consumed_at", "code_digest"])
        if not matches:
            return _error()
        # User lock serializes with upload publication and credential changes.
        vaults = Vault.objects.select_for_update().filter(owner=user)
        list(vaults.values_list("pk", flat=True))
        released = CipherFile.objects.filter(vault__owner=user).aggregate(total=Sum("ciphertext_bytes"))["total"] or 0
        vaults.update(revoked_at=timezone.now(), wrapped_key={})
        CipherFile.objects.filter(vault__owner=user).delete()
        CipherFolder.objects.filter(vault__owner=user).delete()
        PasskeyCredential.objects.filter(user=user).delete()
        PasskeyChallenge.objects.filter(user=user).delete()
        OpaqueChallenge.objects.filter(user=user).delete()
        OpaqueCredential.objects.filter(user=user).delete()
        OtpChallenge.objects.filter(user=user).delete()
        TotpCredential.objects.filter(user=user).delete()
        user.used_bytes = max(0, user.used_bytes - released)
        user.set_unusable_password()
        user.passkey_risk_accepted_at = None
        user.save(update_fields=["password", "used_bytes", "passkey_risk_accepted_at"])
        request.session.flush()
        from accounts.onboarding import begin
        begin(request, user)
        request.session["password_setup_required"] = True
        request.session["passkey_recent_reset"] = {"user_id": user.pk, "authenticated_at": timezone.now().timestamp()}
    audit(request, "passkey.reset_and_files_deleted", actor=user)
    return JsonResponse({"ok": True})
