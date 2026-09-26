from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import ShareLink


SESSION_GRANTS_KEY = "sharing.password_grants"


def session_has_password_access(request, share):
    grants = request.session.get(SESSION_GRANTS_KEY, {})
    grant = grants.get(str(share.pk))
    if not isinstance(grant, dict) or not request.user.is_authenticated:
        return False
    try:
        expires_at = timezone.datetime.fromisoformat(grant.get("expires_at", ""))
    except (TypeError, ValueError):
        return False
    return grant.get("revision") == share.revision and grant.get("user_id") == request.user.pk and expires_at > timezone.now()


def grant_session_password_access(request, share):
    grants = dict(request.session.get(SESSION_GRANTS_KEY, {}))
    grants[str(share.pk)] = {
        "revision": share.revision,
        "user_id": request.user.pk,
        "expires_at": (timezone.now() + timedelta(hours=12)).isoformat(),
    }
    request.session[SESSION_GRANTS_KEY] = grants


def apply_share_changes(share, *, access_mode, expires_at, password="", invalidate_existing=False):
    share.access_mode = access_mode
    share.expires_at = expires_at
    if access_mode == ShareLink.AccessMode.PASSWORD:
        if password:
            share.set_password(password)
    else:
        share.password_hash = ""
    if invalidate_existing:
        share.revision += 1
    share.active = True
    share.full_clean()
    share.save()
    return share


@transaction.atomic
def revoke_share(share):
    locked = ShareLink.objects.select_for_update().get(pk=share.pk)
    locked.active = False
    locked.revision += 1
    locked.save(update_fields=["active", "revision", "updated_at"])
    return locked


@transaction.atomic
def revoke_all_for_file(*, owner, file):
    links = list(ShareLink.objects.select_for_update().filter(owner=owner, file=file, active=True))
    now = timezone.now()
    for link in links:
        link.active = False
        link.revision += 1
        link.updated_at = now
    if links:
        ShareLink.objects.bulk_update(links, ["active", "revision", "updated_at"])
    return len(links)


@transaction.atomic
def revoke_all_for_folder(*, owner, folder):
    links = list(ShareLink.objects.select_for_update().filter(owner=owner, folder=folder, active=True))
    now = timezone.now()
    for link in links:
        link.active = False
        link.revision += 1
        link.updated_at = now
    if links:
        ShareLink.objects.bulk_update(links, ["active", "revision", "updated_at"])
    return len(links)
