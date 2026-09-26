"""Mandatory account gates; factor configuration never creates decryption keys."""
from django.contrib.auth import login
from django.utils import timezone


def state(user):
    from passkeys.models import PasskeyCredential
    from otp_auth.models import TotpCredential
    credentials = PasskeyCredential.objects.filter(user=user, active=True, backup_eligible=True, vault__owner=user, vault__revoked_at__isnull=True)
    telegram = bool(user.telegram_user_id)
    passkey = credentials.exists()
    totp = TotpCredential.objects.filter(user=user).exists()
    step = 'telegram' if not telegram else 'passkey' if not passkey else 'totp' if not totp else None
    return {'onboarding_required': step is not None, 'next_step': step, 'telegram_ready': telegram,
            'passkey_ready': passkey, 'totp_ready': totp,
            'upload_ready': telegram and totp and credentials.filter(backed_up=True).exists()}


def begin(request, user, *, full=False):
    request.session.flush()
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    if full and not state(user)['onboarding_required']:
        request.session['nimbus_access'] = user.pk
    request.session['onboarding'] = {'user_id': user.pk, 'started_at': timezone.now().timestamp()}


def valid(request):
    marker = request.session.get('onboarding')
    return (isinstance(marker, dict) and marker.get('user_id') == request.user.pk
            and type(marker.get('started_at')) in (int, float)
            and 0 <= timezone.now().timestamp() - marker['started_at'] < 900)


def full_access(request):
    return request.session.get('nimbus_access') == request.user.pk
