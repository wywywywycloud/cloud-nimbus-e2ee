"""Opaque folder tree. Names remain encrypted; hierarchy and flags are visible."""
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import CipherFile, CipherFolder, Vault
from .validation import envelope, uuid_value
from .views import User, _available, _error, _json_body, authenticated


def folder_data(item):
    return {"id": str(item.pk), "vault_id": str(item.vault_id), "metadata": item.metadata,
            "parent_id": str(item.parent_id) if item.parent_id else None, "starred": item.starred,
            "trashed_at": item.trashed_at.isoformat() if item.trashed_at else None,
            "created_at": item.created_at.isoformat(), "kind": "folder"}


def live_parent(vault, identifier):
    if identifier is None:
        return None
    parent = CipherFolder.objects.filter(pk=uuid_value(identifier), vault=vault).first()
    seen = set()
    current = parent
    if parent is None:
        raise ValueError("invalid_parent")
    while current:
        if current.pk in seen or current.trashed_at or current.vault_id != vault.pk:
            raise ValueError("invalid_parent")
        seen.add(current.pk)
        current = current.parent
    return parent


def descendants(vault, identifier):
    children = {}
    for key, parent in vault.folders.values_list("pk", "parent_id"):
        children.setdefault(parent, []).append(key)
    result, pending = set(), [identifier]
    while pending:
        key = pending.pop()
        if key in result:
            continue
        result.add(key)
        pending.extend(children.get(key, []))
    return result


@authenticated
@require_http_methods(["GET", "POST"])
def folders(request):
    if request.method == "GET":
        return JsonResponse({"folders": [folder_data(f) for f in CipherFolder.objects.filter(vault__owner=request.user, vault__revoked_at__isnull=True)]})
    try:
        data = _json_body(request)
        if set(data) != {"id", "vault_id", "metadata", "parent_id"}:
            raise ValueError()
        identifier, vault_id, metadata = uuid_value(data["id"]), uuid_value(data["vault_id"]), envelope(data["metadata"])
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            vault = Vault.objects.select_for_update().filter(pk=vault_id, owner=user, revoked_at__isnull=True).first()
            if not _available(user) or vault is None:
                return _error("vault_not_active", 409)
            if vault.folders.count() >= 10000 or CipherFolder.objects.filter(pk=identifier).exists():
                return _error("folder_limit_or_conflict", 409)
            parent = live_parent(vault, data["parent_id"])
            item = CipherFolder.objects.create(id=identifier, vault=vault, parent=parent, metadata=metadata)
        return JsonResponse({"folder": folder_data(item)}, status=201)
    except (ValueError, TypeError):
        return _error("invalid_folder")


@authenticated
@require_http_methods(["PATCH", "DELETE"])
def item(request, kind, identifier):
    if kind not in {"folders", "files"}:
        return _error("item_not_found", 404)
    model = CipherFolder if kind == "folders" else CipherFile
    try:
        data = _json_body(request) if request.method == "PATCH" else {}
        if request.method == "PATCH" and (len(data) != 1 or not set(data) <= {"parent_id", "starred", "trashed", "metadata"}):
            raise ValueError()
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            vault = Vault.objects.select_for_update().filter(owner=user, revoked_at__isnull=True).first()
            target = model.objects.filter(pk=identifier, vault=vault).first() if vault else None
            if not _available(user) or target is None:
                return _error("item_not_found", 404)
            if request.method == "DELETE":
                if target.trashed_at is None:
                    return _error("trash_required", 409)
                if kind == "folders":
                    ids = descendants(vault, target.pk)
                    files = vault.files.filter(parent_id__in=ids)
                else:
                    ids, files = set(), vault.files.filter(pk=target.pk)
                released = files.aggregate(n=Sum("ciphertext_bytes"))["n"] or 0
                files.delete()
                if ids:
                    vault.folders.filter(pk__in=ids).update(parent=None)
                    vault.folders.filter(pk__in=ids).delete()
                user.used_bytes = max(0, user.used_bytes - released)
                user.save(update_fields=["used_bytes"])
                return JsonResponse({"deleted": True})
            if "starred" in data:
                if type(data["starred"]) is not bool:
                    raise ValueError()
                target.starred = data["starred"]
            elif "trashed" in data:
                if type(data["trashed"]) is not bool:
                    raise ValueError()
                if not data["trashed"]:
                    # Restore to root when its former parent is in the trash.
                    try:
                        live_parent(vault, str(target.parent_id) if target.parent_id else None)
                    except ValueError:
                        target.parent = None
                target.trashed_at = timezone.now() if data["trashed"] else None
            elif "parent_id" in data:
                if target.trashed_at:
                    raise ValueError()
                parent = live_parent(vault, data["parent_id"])
                if kind == "folders" and parent and parent.pk in descendants(vault, target.pk):
                    raise ValueError()
                target.parent = parent
            else:
                if kind != "folders":
                    raise ValueError()
                target.metadata = envelope(data["metadata"])
            target.save()
        return JsonResponse({"ok": True})
    except (ValueError, TypeError):
        return _error("invalid_item_change")
