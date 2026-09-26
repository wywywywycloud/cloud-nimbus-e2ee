from django.core.mail import send_mail
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.db import models, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from drive.folder_sizes import attach_folder_sizes
from drive.models import Folder, StoredFile
from drive.storage import open_stored_file
from core.audit import allow_action, client_ip
from core.audit import audit

from .forms import FileGrantForm, ShareLinkForm, ShareLinkUpdateForm, SharePasswordForm
from .models import FileGrant, ShareLink
from .services import (
    apply_share_changes,
    grant_session_password_access,
    revoke_all_for_file,
    revoke_share,
    session_has_password_access,
)


def _owned_file(request, file_id):
    return get_object_or_404(StoredFile, pk=file_id, owner=request.user)


def _owned_share(request, pk):
    return get_object_or_404(ShareLink.objects.select_related("file", "folder"), pk=pk, owner=request.user)


def _owned_target(request, kind, item_id):
    if kind == "file":
        return get_object_or_404(StoredFile, pk=item_id, owner=request.user)
    if kind == "folder":
        return get_object_or_404(Folder, pk=item_id, owner=request.user)
    raise Http404("Объект не найден")


def _target_filter(target):
    return {"folder": target} if isinstance(target, Folder) else {"file": target}


def _active_share(target):
    return ShareLink.objects.filter(**_target_filter(target), active=True).order_by("-updated_at").first()


@login_required
@require_GET
def shared_with_me(request):
    grants = FileGrant.objects.filter(
        models.Q(user=request.user) | models.Q(email__iexact=request.user.email)
    ).select_related("file", "folder", "granted_by")
    file_ids = {grant.file_id for grant in grants if grant.file_id}
    folder_ids = {grant.folder_id for grant in grants if grant.folder_id}
    shares = ShareLink.objects.filter(active=True).filter(
        models.Q(file_id__in=file_ids) | models.Q(folder_id__in=folder_ids)
    ).select_related("file", "folder", "owner").order_by("-updated_at")
    available = {}
    for share in shares:
        owner_available = share.owner.is_active and share.owner.scheduled_deletion_at is None
        if share.is_available and owner_available:
            available.setdefault(("folder" if share.folder_id else "file", share.folder_id or share.file_id), share)

    items = []
    seen = set()
    for grant in grants:
        key = ("folder" if grant.folder_id else "file", grant.folder_id or grant.file_id)
        share = available.get(key)
        if not share or key in seen:
            continue
        seen.add(key)
        target = grant.target
        items.append({
            "kind": key[0],
            "name": target.name if grant.folder_id else target.display_name,
            "owner": share.owner,
            "role": grant.get_role_display(),
            "updated_at": share.updated_at,
            "url": reverse("sharing:public_share", args=[share.public_token]),
        })
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return render(request, "sharing/shared_with_me.html", {"items": items, "active_view": "shared"})


def _serialize_share_state(request, target, kind):
    share = _active_share(target)
    grants = FileGrant.objects.filter(**_target_filter(target)).select_related("user").order_by("email", "user_id")
    return {
        "kind": kind,
        "id": target.pk,
        "name": target.name if kind == "folder" else target.display_name,
        "owner": {"username": request.user.username, "email": request.user.email},
        "general": {
            "mode": share.access_mode if share else ShareLink.AccessMode.RESTRICTED,
            "share_id": str(share.pk) if share else None,
            "url": request.build_absolute_uri(reverse("sharing:public_share", args=[share.public_token])) if share and share.access_mode != ShareLink.AccessMode.RESTRICTED else "",
            "expires_at": share.expires_at.isoformat(timespec="minutes") if share and share.expires_at else "",
            "password_set": bool(share and share.password_hash),
        },
        "grants": [
            {
                "id": grant.pk,
                "email": grant.email,
                "username": grant.user.username if grant.user_id else "",
                "role": grant.role,
            }
            for grant in grants
        ],
    }


@login_required
@require_GET
def item_share_state(request, kind, item_id):
    target = _owned_target(request, kind, item_id)
    return JsonResponse(_serialize_share_state(request, target, kind))


@login_required
@require_POST
def set_general_access(request, kind, item_id):
    target = _owned_target(request, kind, item_id)
    requested_mode = request.POST.get("access_mode", ShareLink.AccessMode.RESTRICTED)
    if requested_mode not in ShareLink.AccessMode.values:
        return JsonResponse({"error": "invalid_access_mode"}, status=400)

    with transaction.atomic():
        links = list(ShareLink.objects.select_for_update().filter(**_target_filter(target), active=True).order_by("-updated_at"))
        has_grants = FileGrant.objects.filter(**_target_filter(target)).exists()
        if requested_mode == ShareLink.AccessMode.RESTRICTED and not has_grants:
            for existing in links:
                revoke_share(existing)
            audit(request, "sharing.general_changed", mode=requested_mode, file_id=target.pk if kind == "file" else None, folder_id=target.pk if kind == "folder" else None)
            return JsonResponse(_serialize_share_state(request, target, kind))
        share = links[0] if links else ShareLink(owner=request.user, **_target_filter(target))
        for duplicate in links[1:]:
            revoke_share(duplicate)
        form = ShareLinkUpdateForm(request.POST, instance=share)
        if not form.is_valid():
            return JsonResponse({"error": "invalid_settings", "fields": form.errors.get_json_data()}, status=400)
        changes = dict(form.cleaned_data)
        invalidate = changes.pop("invalidate_existing", False) or requested_mode == ShareLink.AccessMode.RESTRICTED
        apply_share_changes(share, **changes, invalidate_existing=invalidate)
    audit(request, "sharing.general_changed", share_id=str(share.pk), mode=requested_mode, file_id=getattr(target, "pk", None) if kind == "file" else None, folder_id=getattr(target, "pk", None) if kind == "folder" else None)
    return JsonResponse(_serialize_share_state(request, target, kind))


@login_required
@require_POST
def create_item_grant(request, kind, item_id):
    target = _owned_target(request, kind, item_id)
    form = FileGrantForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "invalid_grant", "fields": form.errors.get_json_data()}, status=400)
    email = get_user_model().objects.normalize_email(form.cleaned_data["email"]).lower()
    if email.casefold() == request.user.email.casefold():
        return JsonResponse(
            {"error": "cannot_share_with_self", "fields": {"email": [{"message": "Вы уже владелец этого объекта."}]}},
            status=400,
        )
    user = get_user_model().objects.filter(email__iexact=email, email_verified=True, is_active=True).first()
    filters = _target_filter(target)
    lookup = models.Q(user=user) if user else models.Q(email__iexact=email)
    grant = FileGrant.objects.filter(**filters).filter(lookup).first()
    if grant:
        grant.user = user
        grant.email = email
        grant.role = form.cleaned_data["role"]
        grant.granted_by = request.user
        grant.full_clean()
        grant.save()
    else:
        grant = FileGrant(granted_by=request.user, user=user, email=email, role=form.cleaned_data["role"], **filters)
        grant.full_clean()
        grant.save()

    share = _active_share(target)
    if not share:
        share = ShareLink(owner=request.user, access_mode=ShareLink.AccessMode.RESTRICTED, **filters)
        share.full_clean()
        share.save()
    share_url = request.build_absolute_uri(reverse("sharing:public_share", args=[share.public_token]))
    # External invitees always need the invitation link. Registered users can
    # opt out because the shared item remains discoverable inside the product.
    if user is None or user.email_share_notifications:
        send_mail(
            f"{request.user.username} открыл доступ в cloud.nimbus",
            f"Вам открыт доступ к «{share.target_name}» с ролью {grant.get_role_display()}.\n{share_url}",
            None,
            [email],
        )
    audit(request, "sharing.grant_changed", grant_id=grant.pk, share_id=str(share.pk), file_id=target.pk if kind == "file" else None, folder_id=target.pk if kind == "folder" else None)
    return JsonResponse(_serialize_share_state(request, target, kind))


def _file_download(item):
    if not item.downloadable:
        raise Http404("Файл недоступен")
    try:
        handle = open_stored_file(item)
    except FileNotFoundError as exc:
        raise Http404("Файл не найден в хранилище") from exc
    response = FileResponse(
        handle,
        as_attachment=True,
        filename=item.display_name,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_GET
def file_shares(request, file_id):
    item = _owned_file(request, file_id)
    return render(
        request,
        "sharing/manage.html",
        {"file": item, "links": item.share_links.filter(owner=request.user), "grants": item.grants.select_related("user"), "create_form": ShareLinkForm(), "grant_form": FileGrantForm()},
    )


@login_required
@require_POST
def create_share(request, file_id):
    item = _owned_file(request, file_id)
    form = ShareLinkForm(request.POST)
    if form.is_valid():
        share = ShareLink(owner=request.user, file=item)
        apply_share_changes(share, **form.cleaned_data)
        messages.success(request, "Ссылка создана.")
    else:
        messages.error(request, "Не удалось создать ссылку: проверьте параметры.")
    return redirect("sharing:file_shares", file_id=item.pk)


@login_required
@require_POST
def update_share(request, pk):
    share = get_object_or_404(ShareLink.objects.select_related("file"), pk=pk, owner=request.user, active=True)
    form = ShareLinkUpdateForm(request.POST, instance=share)
    if form.is_valid():
        apply_share_changes(share, **form.cleaned_data)
        messages.success(request, "Настройки ссылки обновлены.")
    else:
        messages.error(request, "Не удалось обновить ссылку: проверьте параметры.")
    return redirect("sharing:file_shares", file_id=share.file_id)


@login_required
@require_POST
def revoke_share_link(request, pk):
    share = _owned_share(request, pk)
    revoke_share(share)
    messages.success(request, "Ссылка отозвана.")
    return redirect("sharing:file_shares", file_id=share.file_id)


@login_required
@require_POST
def revoke_all_share_links(request, file_id):
    item = _owned_file(request, file_id)
    count = revoke_all_for_file(owner=request.user, file=item)
    messages.success(request, f"Отозвано ссылок: {count}.")
    return redirect("sharing:file_shares", file_id=item.pk)


@login_required
@require_POST
def create_grant(request, file_id):
    item = _owned_file(request, file_id)
    form = FileGrantForm(request.POST)
    if form.is_valid():
        email = get_user_model().objects.normalize_email(form.cleaned_data["email"]).lower()
        user = get_user_model().objects.filter(email__iexact=email, email_verified=True, is_active=True).first()
        grant = FileGrant.objects.filter(file=item).filter(models.Q(user=user) if user else models.Q(email__iexact=email)).first()
        if grant:
            grant.user = user
            grant.email = email
            grant.role = form.cleaned_data["role"]
            grant.granted_by = request.user
            grant.save()
        else:
            FileGrant.objects.create(file=item, granted_by=request.user, user=user, email=email, role=form.cleaned_data["role"])
        messages.success(request, "Доступ пользователя обновлён.")
    else:
        messages.error(request, "Проверьте почту и роль.")
    return redirect("sharing:file_shares", file_id=item.pk)


@login_required
@require_POST
def revoke_grant(request, pk):
    grant = get_object_or_404(FileGrant, pk=pk, granted_by=request.user)
    file_id = grant.file_id
    folder_id = grant.folder_id
    target = grant.target
    kind = "folder" if grant.folder_id else "file"
    grant.delete()
    if not FileGrant.objects.filter(**_target_filter(target)).exists():
        share = _active_share(target)
        if share and share.access_mode == ShareLink.AccessMode.RESTRICTED:
            revoke_share(share)
    audit(request, "sharing.grant_revoked", grant_id=pk, file_id=file_id, folder_id=folder_id)
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(_serialize_share_state(request, target, kind))
    messages.success(request, "Персональный доступ отозван.")
    if folder_id:
        return redirect("drive:folder", folder_id=folder_id)
    return redirect("drive:folder", folder_id=target.folder_id) if target.folder_id else redirect("drive:home")


def _share_grants(share):
    return share.folder.grants if share.folder_id else share.file.grants


def _share_gate(request, share, *, password_post=False):
    owner_available = share.owner.is_active and share.owner.scheduled_deletion_at is None
    if not share.is_available or not owner_available:
        raise Http404("Ссылка недоступна")
    if share.access_mode == ShareLink.AccessMode.ANYONE:
        return None
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if request.user.pk == share.owner_id or share.access_mode == ShareLink.AccessMode.SIGNED_IN:
        return None
    if share.access_mode == ShareLink.AccessMode.RESTRICTED:
        allowed = _share_grants(share).filter(models.Q(user=request.user) | models.Q(email__iexact=request.user.email)).exists()
        if not allowed:
            raise Http404("Ссылка недоступна")
        return None
    if session_has_password_access(request, share):
        return None
    if not password_post:
        return redirect("sharing:public_share", token=share.public_token)
    return "password_required"


def _folder_contains(root, candidate):
    current = candidate
    seen = set()
    while current:
        if current.pk == root.pk:
            return True
        if current.pk in seen or current.owner_id != root.owner_id:
            return False
        seen.add(current.pk)
        current = current.parent
    return False


def _render_shared_folder(request, share, current):
    if not _folder_contains(share.folder, current):
        raise Http404("Папка недоступна")
    folders = attach_folder_sizes(share.owner, current.children.filter(owner=share.owner).order_by("name"))
    files = current.stored_files.filter(owner=share.owner).order_by("display_name")
    breadcrumbs = []
    node = current
    while node and _folder_contains(share.folder, node):
        breadcrumbs.append(node)
        if node.pk == share.folder_id:
            break
        node = node.parent
    breadcrumbs.reverse()
    response = render(request, "sharing/folder.html", {"share": share, "current_folder": current, "folders": folders, "files": files, "breadcrumbs": breadcrumbs, "active_view": "shared"})
    response["Cache-Control"] = "private, no-store"
    # HTML pages contain authenticated POST controls in the application shell.
    # Sending only the origin keeps the capability path private without
    # producing Origin: null, which browsers correctly reject under CSRF.
    response["Referrer-Policy"] = "origin"
    return response


@require_http_methods(["GET", "POST"])
def public_share(request, token):
    share = ShareLink.resolve_token(token)
    if not share:
        raise Http404("Ссылка недоступна")
    gate = _share_gate(request, share, password_post=True)
    if gate == "password_required":
        form = SharePasswordForm(request.POST or None)
        rate_key = f"{client_ip(request)}:{share.pk}"
        if request.method == "POST" and not allow_action("share_password", rate_key, limit=10, window_seconds=900):
            form.add_error("password", "Слишком много попыток. Попробуйте через 15 минут.")
        elif request.method == "POST" and form.is_valid():
            if share.check_password(form.cleaned_data["password"]):
                grant_session_password_access(request, share)
                return redirect("sharing:public_share", token=share.public_token)
            form.add_error("password", "Неверный пароль ссылки.")
        response = render(request, "sharing/password.html", {"share": share, "form": form})
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "origin"
        return response
    if gate is not None:
        return gate
    if share.folder_id:
        return _render_shared_folder(request, share, share.folder)
    return _file_download(share.file)


@require_GET
def public_share_folder(request, token, folder_id):
    share = ShareLink.resolve_token(token)
    if not share or not share.folder_id:
        raise Http404("Ссылка недоступна")
    gate = _share_gate(request, share)
    if gate is not None:
        return gate
    current = get_object_or_404(Folder.objects.select_related("parent"), pk=folder_id, owner=share.owner)
    return _render_shared_folder(request, share, current)


@require_GET
def public_share_file(request, token, file_id):
    share = ShareLink.resolve_token(token)
    if not share or not share.folder_id:
        raise Http404("Ссылка недоступна")
    gate = _share_gate(request, share)
    if gate is not None:
        return gate
    item = get_object_or_404(StoredFile.objects.select_related("folder"), pk=file_id, owner=share.owner)
    if not item.folder_id or not _folder_contains(share.folder, item.folder):
        raise Http404("Файл недоступен")
    return _file_download(item)
