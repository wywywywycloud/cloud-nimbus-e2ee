import hashlib
import json
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import RestrictedError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User
from core.audit import audit
from .folder_sizes import attach_folder_sizes
from .forms import FolderNameForm, MAX_USER_BYTES, RenameForm, UploadForm
from .models import Folder, StoredFile, UploadSession
from .security import scan_path
from .storage import open_stored_file


@login_required
def home(request):
    if not settings.NIMBUS_LEGACY_WRITES_ENABLED and request.GET.get("legacy") != "1":
        return redirect("/vault/")
    return _browse(request)


@login_required
def folder(request, folder_id):
    current_folder = get_object_or_404(Folder.objects.select_related("parent"), pk=folder_id, owner=request.user)
    return _browse(request, current_folder=current_folder)


def _browse(request, current_folder=None):
    if not request.user.email_verified:
        return redirect("accounts:verify_email")
    files = StoredFile.objects.filter(owner=request.user)
    folders = Folder.objects.filter(owner=request.user, parent=current_folder)
    query = request.GET.get("q", "").strip()
    view = request.GET.get("view", "files")
    if query:
        files = files.filter(display_name__icontains=query)
    if view == "favorites":
        files = files.filter(favorite=True)
        folders = folders.none()
    elif view == "recent":
        files = files.order_by("-updated_at")[:20]
        folders = folders.none()
    else:
        files = files.filter(folder=current_folder)
    if query:
        folders = folders.filter(name__icontains=query)
    folders = attach_folder_sizes(request.user, folders)
    files = list(files)

    browser_items = [
        {
            "kind": "folder",
            "object": item,
            "name": item.name,
            "size": item.total_size_bytes,
            "updated_at": item.updated_at,
        }
        for item in folders
    ] + [
        {
            "kind": "file",
            "object": item,
            "name": item.display_name,
            "size": item.size,
            "updated_at": item.updated_at,
        }
        for item in files
    ]

    if view == "recent":
        browser_items.sort(key=lambda item: item["updated_at"], reverse=True)
    elif request.user.default_file_sort == User.FileSort.MODIFIED:
        browser_items.sort(key=lambda item: item["updated_at"], reverse=True)
    elif request.user.default_file_sort == User.FileSort.SIZE:
        browser_items.sort(key=lambda item: (-item["size"], item["name"].casefold()))
    else:
        browser_items.sort(key=lambda item: item["name"].casefold())

    if request.user.folders_first and view not in {"favorites", "recent"}:
        browser_items.sort(key=lambda item: item["kind"] != "folder")
    breadcrumbs = current_folder.breadcrumbs() if current_folder else []
    return render(
        request,
        "drive/home.html",
        {
            "files": files,
            "folders": folders,
            "browser_items": browser_items,
            "query": query,
            "active_view": view,
            "current_folder": current_folder,
            "parent_folder": current_folder.parent if current_folder else None,
            "breadcrumbs": breadcrumbs,
            "upload_form": UploadForm(user=request.user, initial={"folder": current_folder}),
            "create_folder_form": FolderNameForm(owner=request.user, parent=current_folder),
        },
    )


def _redirect_to_folder(folder):
    if folder is None:
        return redirect("drive:home")
    return redirect("drive:folder", folder_id=folder.pk)


@login_required
@require_POST
def create_folder(request):
    parent = None
    parent_id = request.POST.get("parent")
    if parent_id:
        parent = get_object_or_404(Folder, pk=parent_id, owner=request.user)
    form = FolderNameForm(request.POST, owner=request.user, parent=parent)
    if form.is_valid():
        try:
            Folder.objects.create(owner=request.user, parent=parent, name=form.cleaned_data["name"])
        except (IntegrityError, ValidationError):
            messages.error(request, "Папка с таким именем уже существует здесь.")
        else:
            messages.success(request, "Папка создана.")
            audit(request, "folder.created", parent_id=parent.pk if parent else None)
    else:
        messages.error(request, " ".join(form.errors.get("name", [])) or "Введите корректное имя папки.")
    return _redirect_to_folder(parent)


@login_required
@require_POST
def rename_folder(request, pk):
    item = get_object_or_404(Folder.objects.select_related("parent"), pk=pk, owner=request.user)
    form = FolderNameForm(request.POST, owner=request.user, parent=item.parent, instance=item)
    if form.is_valid():
        item.name = form.cleaned_data["name"]
        try:
            item.save(update_fields=["name", "updated_at"])
        except (IntegrityError, ValidationError):
            messages.error(request, "Папка с таким именем уже существует здесь.")
        else:
            messages.success(request, "Папка переименована.")
            audit(request, "folder.renamed", folder_id=item.pk)
    else:
        messages.error(request, " ".join(form.errors.get("name", [])) or "Введите корректное имя папки.")
    return _redirect_to_folder(item.parent)


@login_required
@require_POST
def delete_folder(request, pk):
    parent = None
    with transaction.atomic():
        item = get_object_or_404(Folder.objects.select_for_update().select_related("parent"), pk=pk, owner=request.user)
        parent = item.parent
        if item.children.exists() or item.stored_files.exists():
            messages.error(request, "Удалить можно только пустую папку.")
            return _redirect_to_folder(parent)
        try:
            item.delete()
        except RestrictedError:
            messages.error(request, "Удалить можно только пустую папку.")
            return _redirect_to_folder(parent)
    messages.success(request, "Папка удалена.")
    audit(request, "folder.deleted", folder_id=pk)
    return _redirect_to_folder(parent)


@login_required
@require_POST
def upload(request):
    if not settings.NIMBUS_LEGACY_WRITES_ENABLED:
        return JsonResponse({"error": "plaintext_upload_disabled", "client": "/vault/"}, status=410)
    form = UploadForm(request.POST, request.FILES, user=request.user)
    if not form.is_valid():
        messages.error(request, " ".join(form.non_field_errors()) or "Не удалось загрузить файлы.")
        return redirect("drive:home")
    uploaded = []
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if settings.TELEGRAM_ENABLED and not user.telegram_user_id:
                raise ValueError("Подтвердите Telegram в настройках, чтобы загружать файлы.")
            files = form.cleaned_data["uploaded_files"]
            target_folder = form.cleaned_data.get("folder")
            total = sum(file.size for file in files)
            if user.used_bytes + user.reserved_bytes + total > user.quota_bytes:
                raise ValueError("Квота изменилась. Обновите страницу и попробуйте снова.")
            for incoming in files:
                item = StoredFile(
                    owner=user,
                    folder=target_folder,
                    display_name=Path(incoming.name).name[:255],
                    size=incoming.size,
                    content_type=(incoming.content_type or "application/octet-stream")[:255],
                )
                item.blob.save(incoming.name, incoming, save=False)
                item.object_key = item.blob.name
                item.save()
                uploaded.append(item)
                try:
                    status, report, checksum = scan_path(item.blob.path)
                except (NotImplementedError, AttributeError):
                    status, report, checksum = StoredFile.ScanStatus.ERROR, "Storage backend cannot be scanned locally", ""
                item.scan_status = status
                item.scan_report = report
                item.checksum_sha256 = checksum
                item.save(update_fields=["scan_status", "scan_report", "checksum_sha256", "object_key", "updated_at"])
            user.used_bytes += total
            user.save(update_fields=["used_bytes"])
    except Exception as exc:
        for item in uploaded:
            item.blob.delete(save=False)
        messages.error(request, str(exc) if isinstance(exc, ValueError) else "Загрузка не завершена.")
        return redirect("drive:home")
    messages.success(request, f"Загружено файлов: {len(uploaded)}.")
    audit(request, "file.uploaded", count=len(uploaded), bytes=sum(item.size for item in uploaded))
    return _redirect_to_folder(target_folder)


@login_required
def download(request, pk):
    item = get_object_or_404(StoredFile, pk=pk, owner=request.user)
    if not item.downloadable:
        messages.error(request, "Файл недоступен, пока антивирусная проверка не завершена.")
        return redirect("drive:home")
    try:
        handle = open_stored_file(item)
    except FileNotFoundError as exc:
        raise Http404("Файл не найден в хранилище") from exc
    response = FileResponse(handle, as_attachment=True, filename=item.display_name, content_type="application/octet-stream")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    audit(request, "file.downloaded", file_id=item.pk)
    return response


@login_required
@require_GET
def preview(request, pk):
    item = get_object_or_404(StoredFile, pk=pk, owner=request.user)
    if not item.previewable:
        raise Http404("Предпросмотр недоступен")
    try:
        handle = open_stored_file(item)
    except FileNotFoundError as exc:
        raise Http404("Файл не найден в хранилище") from exc
    response = FileResponse(handle, as_attachment=False, filename=item.display_name, content_type=item.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@login_required
@require_POST
def rename(request, pk):
    item = get_object_or_404(StoredFile.objects.select_related("folder"), pk=pk, owner=request.user)
    form = RenameForm(request.POST)
    if form.is_valid():
        item.display_name = form.cleaned_data["name"]
        item.save(update_fields=["display_name", "updated_at"])
        messages.success(request, "Файл переименован.")
    else:
        messages.error(request, "Введите корректное имя.")
    return _redirect_to_folder(item.folder)


@login_required
@require_POST
def favorite(request, pk):
    item = get_object_or_404(StoredFile, pk=pk, owner=request.user)
    item.favorite = not item.favorite
    item.save(update_fields=["favorite", "updated_at"])
    return redirect(request.POST.get("next") or "drive:home")


@login_required
@require_POST
def delete(request, pk):
    parent = None
    with transaction.atomic():
        item = get_object_or_404(StoredFile.objects.select_for_update().select_related("folder"), pk=pk, owner=request.user)
        parent = item.folder
        user = User.objects.select_for_update().get(pk=request.user.pk)
        size = item.size
        blob = item.blob
        item.delete()
        user.used_bytes = max(0, user.used_bytes - size)
        user.save(update_fields=["used_bytes"])
        transaction.on_commit(lambda: blob.delete(save=False))
    messages.success(request, "Файл удалён.")
    audit(request, "file.deleted", file_id=pk, bytes=size)
    return _redirect_to_folder(parent)


def _parts_dir(upload):
    return Path(settings.MEDIA_ROOT) / "upload-parts" / str(upload.owner_id) / str(upload.pk)


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


@login_required
@require_POST
def upload_initiate(request):
    if not settings.NIMBUS_LEGACY_WRITES_ENABLED:
        return JsonResponse({"error": "plaintext_upload_disabled", "client": "/vault/"}, status=410)
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "invalid_json"}, status=400)
    try:
        total_size = int(payload.get("size", 0))
    except (TypeError, ValueError):
        total_size = 0
    display_name = Path(str(payload.get("name", ""))).name[:255]
    idempotency_key = request.headers.get("Idempotency-Key", "")[:64]
    folder_id = payload.get("folder_id")
    target_folder = None
    if folder_id not in (None, ""):
        target_folder = get_object_or_404(Folder, pk=folder_id, owner=request.user)
    if not display_name or total_size <= 0 or total_size > settings.MAX_SINGLE_UPLOAD_BYTES:
        return JsonResponse({"error": "invalid_file", "max_bytes": settings.MAX_SINGLE_UPLOAD_BYTES}, status=400)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if settings.TELEGRAM_ENABLED and not user.telegram_user_id:
            return JsonResponse(
                {"error": "telegram_required", "remaining_bytes": max(0, user.quota_bytes - user.used_bytes - user.reserved_bytes)},
                status=409,
            )
        if idempotency_key:
            existing = UploadSession.objects.filter(owner=user, idempotency_key=idempotency_key).first()
            if existing:
                if existing.total_size != total_size or existing.display_name != display_name or existing.folder_id != (target_folder.pk if target_folder else None):
                    return JsonResponse({"error": "idempotency_conflict"}, status=409)
                return JsonResponse({"upload_id": str(existing.pk), "chunk_size": existing.chunk_size, "total_size": existing.total_size, "expires_at": existing.expires_at.isoformat(), "state": existing.state})
        if user.used_bytes + user.reserved_bytes + total_size > user.quota_bytes:
            return JsonResponse({"error": "quota_exceeded", "remaining_bytes": max(0, user.quota_bytes - user.used_bytes - user.reserved_bytes)}, status=409)
        target_chunk = (total_size + 8999) // 9000
        chunk_size = max(settings.UPLOAD_CHUNK_BYTES, target_chunk)
        mebibyte = 1024 * 1024
        chunk_size = ((chunk_size + mebibyte - 1) // mebibyte) * mebibyte
        upload = UploadSession.objects.create(
            owner=user,
            folder=target_folder,
            display_name=display_name,
            content_type=str(payload.get("content_type") or "application/octet-stream")[:255],
            total_size=total_size,
            chunk_size=chunk_size,
            idempotency_key=idempotency_key,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        user.reserved_bytes += total_size
        user.save(update_fields=["reserved_bytes"])
    audit(request, "upload.initiated", bytes=total_size)
    return JsonResponse({"upload_id": str(upload.pk), "chunk_size": upload.chunk_size, "total_size": upload.total_size, "expires_at": upload.expires_at.isoformat()})


@login_required
@require_GET
def upload_status(request, upload_id):
    upload = get_object_or_404(UploadSession, pk=upload_id, owner=request.user)
    return JsonResponse({"upload_id": str(upload.pk), "state": upload.state, "received_parts": upload.received_parts, "chunk_size": upload.chunk_size, "total_size": upload.total_size})


@login_required
@require_http_methods(["PUT"])
def upload_part(request, upload_id, part_number):
    if not settings.NIMBUS_LEGACY_WRITES_ENABLED:
        return JsonResponse({"error": "plaintext_upload_disabled"}, status=410)
    with transaction.atomic():
        upload = get_object_or_404(UploadSession.objects.select_for_update(), pk=upload_id, owner=request.user)
        if upload.state != UploadSession.State.UPLOADING or upload.expires_at <= timezone.now():
            return JsonResponse({"error": "upload_not_active"}, status=409)
        expected_parts = (upload.total_size + upload.chunk_size - 1) // upload.chunk_size
        if part_number < 0 or part_number >= expected_parts:
            return JsonResponse({"error": "invalid_part"}, status=400)
        expected_size = min(upload.chunk_size, upload.total_size - part_number * upload.chunk_size)
        part_dir = _parts_dir(upload)
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / f"{part_number:08d}.part"
        temp_path = part_path.with_suffix(".tmp")
        digest = hashlib.sha256()
        written = 0
        with temp_path.open("wb") as target:
            while True:
                chunk = request.read(min(1024 * 1024, expected_size - written + 1))
                if not chunk:
                    break
                written += len(chunk)
                if written > expected_size:
                    target.close()
                    temp_path.unlink(missing_ok=True)
                    return JsonResponse({"error": "part_too_large"}, status=413)
                digest.update(chunk)
                target.write(chunk)
        if written != expected_size:
            temp_path.unlink(missing_ok=True)
            return JsonResponse({"error": "part_size_mismatch", "expected": expected_size, "received": written}, status=400)
        claimed = request.headers.get("X-Chunk-SHA256", "")
        if claimed and claimed.lower() != digest.hexdigest():
            temp_path.unlink(missing_ok=True)
            return JsonResponse({"error": "checksum_mismatch"}, status=400)
        temp_path.replace(part_path)
        parts = set(upload.received_parts)
        parts.add(part_number)
        upload.received_parts = sorted(parts)
        upload.save(update_fields=["received_parts", "updated_at"])
    return JsonResponse({"part": part_number, "sha256": digest.hexdigest(), "received_parts": upload.received_parts})


@login_required
@require_POST
def upload_complete(request, upload_id):
    if not settings.NIMBUS_LEGACY_WRITES_ENABLED:
        return JsonResponse({"error": "plaintext_upload_disabled"}, status=410)
    with transaction.atomic():
        upload = get_object_or_404(UploadSession.objects.select_for_update(), pk=upload_id, owner=request.user)
        expected_parts = (upload.total_size + upload.chunk_size - 1) // upload.chunk_size
        if upload.state != UploadSession.State.UPLOADING or upload.received_parts != list(range(expected_parts)):
            return JsonResponse({"error": "missing_parts", "received_parts": upload.received_parts}, status=409)
        upload.state = UploadSession.State.ASSEMBLING
        upload.save(update_fields=["state", "updated_at"])

    part_dir = _parts_dir(upload)
    assembled = part_dir / "assembled.tmp"
    item = None
    try:
        with assembled.open("wb") as target:
            for part_number in range(expected_parts):
                with (part_dir / f"{part_number:08d}.part").open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        if assembled.stat().st_size != upload.total_size:
            raise ValueError("assembled_size_mismatch")
        item = StoredFile(owner=request.user, folder=upload.folder, display_name=upload.display_name, size=upload.total_size, content_type=upload.content_type)
        with assembled.open("rb") as handle:
            item.blob.save(upload.display_name, File(handle), save=False)
        item.object_key = item.blob.name
        status, report, checksum = scan_path(item.blob.path)
        item.scan_status = status
        item.scan_report = report
        item.checksum_sha256 = checksum
        with transaction.atomic():
            locked_upload = UploadSession.objects.select_for_update().get(pk=upload.pk)
            user = User.objects.select_for_update().get(pk=request.user.pk)
            item.save()
            user.reserved_bytes = max(0, user.reserved_bytes - upload.total_size)
            user.used_bytes += upload.total_size
            user.save(update_fields=["reserved_bytes", "used_bytes"])
            locked_upload.state = UploadSession.State.COMPLETE
            locked_upload.backend_upload_id = item.blob.name
            locked_upload.save(update_fields=["state", "backend_upload_id", "updated_at"])
            transaction.on_commit(lambda: shutil.rmtree(part_dir, ignore_errors=True))
    except Exception:
        if item and item.blob:
            item.blob.delete(save=False)
        with transaction.atomic():
            failed = UploadSession.objects.select_for_update().get(pk=upload.pk)
            user = User.objects.select_for_update().get(pk=request.user.pk)
            failed.state = UploadSession.State.FAILED
            failed.save(update_fields=["state", "updated_at"])
            user.reserved_bytes = max(0, user.reserved_bytes - upload.total_size)
            user.save(update_fields=["reserved_bytes"])
        return JsonResponse({"error": "assembly_failed"}, status=500)
    audit(request, "file.uploaded", count=1, bytes=upload.total_size)
    return JsonResponse({"file_id": item.pk, "name": item.display_name, "scan_status": item.scan_status})


@login_required
@require_POST
def upload_abort(request, upload_id):
    with transaction.atomic():
        upload = get_object_or_404(UploadSession.objects.select_for_update(), pk=upload_id, owner=request.user)
        if upload.state not in {UploadSession.State.UPLOADING, UploadSession.State.FAILED}:
            return JsonResponse({"error": "cannot_abort"}, status=409)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if upload.state == UploadSession.State.UPLOADING:
            user.reserved_bytes = max(0, user.reserved_bytes - upload.total_size)
            user.save(update_fields=["reserved_bytes"])
        upload.state = UploadSession.State.ABORTED
        upload.save(update_fields=["state", "updated_at"])
        transaction.on_commit(lambda: shutil.rmtree(_parts_dir(upload), ignore_errors=True))
    return JsonResponse({"state": upload.state})
