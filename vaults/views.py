import json
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import FileResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import BlobDeletion, CipherFile, Vault
from .services import queue_blob_deletion
from .validation import MAX_CIPHERTEXT_BYTES, MAX_METADATA_BYTES, envelope, uuid_value

User = get_user_model()


def _error(code, status=400):
    return JsonResponse({"error": code}, status=status)


def _available(user):
    return user.is_authenticated and user.is_active and user.scheduled_deletion_at is None


def authenticated(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not _available(request.user):
            return _error("authentication_required", 401)
        return view(request, *args, **kwargs)
    return wrapped


def _json_body(request):
    if request.content_type != "application/json" or len(request.body) > 16 * 1024:
        raise ValueError("invalid_json")
    try:
        result = json.loads(request.body)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(result, dict):
        raise ValueError("invalid_json")
    return result


def _vault_data(vault):
    return {"id": str(vault.pk), "version": vault.version, "wrapped_key": vault.wrapped_key}


def _passkey_ready(user, vault):
    from passkeys.models import PasskeyCredential
    return vault is not None and PasskeyCredential.objects.filter(user=user, vault=vault, active=True, backup_eligible=True, backed_up=True).exists()


def _file_data(item):
    return {
        "id": str(item.pk),
        "vault_id": str(item.vault_id),
        "metadata": item.metadata,
        "ciphertext_bytes": item.ciphertext_bytes,
        "created_at": item.created_at.isoformat(),
    }


@ensure_csrf_cookie
@never_cache
@require_GET
def session(request):
    from otp_auth.models import TotpCredential
    from accounts.onboarding import state, full_access, valid
    from django.contrib.auth import logout

    if _available(request.user):
        gates = state(request.user)
        if (not gates["onboarding_required"] and not full_access(request)) or (gates["onboarding_required"] and not valid(request)):
            logout(request)
    token = get_token(request)
    if not _available(request.user):
        return JsonResponse({"authenticated": False, "csrf_token": token, "user": None, "quota_bytes": 0, "used_bytes": 0, "vault": None, "passkey_ready": False})
    user = User.objects.get(pk=request.user.pk)
    vault = Vault.objects.filter(owner=user, revoked_at__isnull=True).first()
    return JsonResponse({
        "authenticated": True,
        "csrf_token": token,
        "user": {"username": user.username},
        **state(user),
        "password_setup_required": bool(request.session.get("password_setup_required")),
        "quota_bytes": user.quota_bytes,
        "used_bytes": user.used_bytes,
        "reserved_bytes": user.reserved_bytes,
        "vault": _vault_data(vault) if vault else None,
        "otp_method": "totp" if TotpCredential.objects.filter(user=user).exists() else None,
    })


@authenticated
@require_POST
def create_vault(request):
    try:
        payload = _json_body(request)
        if set(payload) != {"id", "version", "wrapped_key"} or type(payload.get("version")) is not int or payload["version"] != 1:
            raise ValueError("invalid_vault")
        vault_id = uuid_value(payload["id"])
        wrapped_key = envelope(payload["wrapped_key"], wrapped_key=True)
    except (ValueError, TypeError):
        return _error("invalid_vault")
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if not _available(user):
                return _error("authentication_required", 401)
            if not user.telegram_user_id:
                return _error("telegram_required", 403)
            if Vault.objects.filter(owner=user, revoked_at__isnull=True).exists():
                return _error("vault_exists", 409)
            if Vault.objects.filter(pk=vault_id).exists():
                return _error("vault_id_unavailable", 409)
            vault = Vault.objects.create(id=vault_id, owner=user, version=1, wrapped_key=wrapped_key)
    except IntegrityError:
        return _error("vault_exists", 409)
    return JsonResponse({"vault": _vault_data(vault)}, status=201)


@authenticated
@require_http_methods(["GET", "POST"])
def files(request):
    if request.method == "GET":
        items = CipherFile.objects.filter(vault__owner=request.user, vault__revoked_at__isnull=True)
        return JsonResponse({"files": [_file_data(item) for item in items]})
    return _upload(request)


def _upload(request):
    try:
        if set(request.POST) - {"vault_id", "id", "metadata", "csrfmiddlewaretoken"} or set(request.FILES) != {"file"}:
            raise ValueError("invalid_upload")
        if any(len(request.POST.getlist(field)) != 1 for field in ("vault_id", "id", "metadata")) or len(request.FILES.getlist("file")) != 1:
            raise ValueError("invalid_upload")
        vault_id = uuid_value(request.POST["vault_id"])
        file_id = uuid_value(request.POST["id"])
        raw_metadata = request.POST["metadata"]
        if len(raw_metadata.encode()) > MAX_METADATA_BYTES:
            raise ValueError("metadata_too_large")
        metadata = envelope(json.loads(raw_metadata))
        incoming = request.FILES["file"]
        if incoming.size < 16 or incoming.size > MAX_CIPHERTEXT_BYTES:
            return _error("invalid_ciphertext_size", 413)
    except (KeyError, ValueError, TypeError, RecursionError):
        return _error("invalid_upload")

    from accounts.onboarding import state
    if not state(request.user)["upload_ready"]:
        return _error("onboarding_required", 403)
    active_vault = Vault.objects.filter(pk=vault_id, owner=request.user, revoked_at__isnull=True).first()
    if active_vault is None:
        return _error("vault_not_active", 409)
    if not _passkey_ready(request.user, active_vault):
        return _error("passkey_required", 409)
    if CipherFile.objects.filter(pk=file_id).exists():
        return _error("file_exists", 409)
    user = User.objects.get(pk=request.user.pk)
    if user.used_bytes + user.reserved_bytes + incoming.size > user.quota_bytes:
        return _error("quota_exceeded", 409)

    # Keep storage I/O outside account/vault locks. The durable staging record
    # also collects a partial blob if this process dies before publication.
    storage_key = f"cypher/{vault_id}/{uuid.uuid4()}.bin"
    staging = BlobDeletion.objects.create(storage_key=storage_key, not_before=timezone.now() + timedelta(hours=24))
    try:
        saved_key = default_storage.save(storage_key, incoming)
        if saved_key != storage_key:
            # UUID collisions are improbable, but a storage adapter may rename.
            staging.storage_key = saved_key
            staging.save(update_fields=["storage_key"])
            storage_key = saved_key
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            vault = Vault.objects.select_for_update().filter(pk=vault_id, owner=user, revoked_at__isnull=True).first()
            if not _available(user):
                response = _error("authentication_required", 401)
            elif vault is None:
                response = _error("vault_not_active", 409)
            elif not _passkey_ready(user, vault):
                response = _error("passkey_required", 409)
            elif not state(user)["upload_ready"]:
                response = _error("onboarding_required", 403)
            elif user.used_bytes + user.reserved_bytes + incoming.size > user.quota_bytes:
                response = _error("quota_exceeded", 409)
            elif CipherFile.objects.filter(pk=file_id).exists():
                response = _error("file_exists", 409)
            else:
                pending = BlobDeletion.objects.select_for_update().filter(pk=staging.pk).first()
                if pending is None:
                    response = _error("upload_expired", 409)
                else:
                    item = CipherFile.objects.create(id=file_id, vault=vault, metadata=metadata, ciphertext_bytes=incoming.size, storage_key=storage_key)
                    user.used_bytes += incoming.size
                    user.save(update_fields=["used_bytes"])
                    pending.delete()
                    return JsonResponse({"file": _file_data(item)}, status=201)
    except IntegrityError:
        response = _error("file_exists", 409)
    except Exception:
        response = _error("upload_failed", 500)
    queue_blob_deletion(storage_key)
    return response


@authenticated
@require_GET
def download(request, file_id):
    item = CipherFile.objects.filter(pk=file_id, vault__owner=request.user, vault__revoked_at__isnull=True).first()
    if item is None:
        return _error("file_not_found", 404)
    try:
        handle = default_storage.open(item.storage_key, "rb")
    except FileNotFoundError:
        return _error("file_not_found", 404)
    response = FileResponse(handle, as_attachment=True, filename=f"{item.pk}.bin", content_type="application/octet-stream")
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Length"] = item.ciphertext_bytes
    return response


@authenticated
@require_http_methods(["DELETE"])
def delete_file(request, file_id):
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        vault = Vault.objects.select_for_update().filter(owner=user, revoked_at__isnull=True).first()
        if not _available(user):
            return _error("authentication_required", 401)
        item = CipherFile.objects.filter(pk=file_id, vault=vault).first() if vault else None
        if item is None:
            return _error("file_not_found", 404)
        user.used_bytes = max(0, user.used_bytes - item.ciphertext_bytes)
        user.save(update_fields=["used_bytes"])
        item.delete()
    return JsonResponse({"deleted": True})


@authenticated
@require_POST
def reset(request):
    from passkeys.models import PasskeyCredential

    try:
        payload = _json_body(request)
        if set(payload) != {"vault_id", "confirmation"} or payload["confirmation"] != "DELETE":
            raise ValueError("invalid_confirmation")
        vault_id = uuid_value(payload["vault_id"])
    except (ValueError, TypeError):
        return _error("invalid_confirmation")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        vault = Vault.objects.select_for_update().filter(pk=vault_id, owner=user, revoked_at__isnull=True).first()
        if not _available(user):
            return _error("authentication_required", 401)
        if vault is None:
            return _error("vault_not_active", 409)
        released = vault.files.aggregate(total=Sum("ciphertext_bytes"))["total"] or 0
        vault.revoked_at = timezone.now()
        vault.wrapped_key = {}
        vault.save(update_fields=["revoked_at", "wrapped_key"])
        vault.files.all().delete()
        PasskeyCredential.objects.filter(user=user, vault=vault).delete()
        user.used_bytes = max(0, user.used_bytes - released)
        user.save(update_fields=["used_bytes"])
    pending = BlobDeletion.objects.filter(storage_key__startswith=f"cypher/{vault_id}/").count()
    return JsonResponse({"deleted": True, "cleanup_pending": pending})
