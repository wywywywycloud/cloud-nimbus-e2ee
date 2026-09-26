"""Explicit completed-factor fixtures for tests outside the onboarding protocol."""
import uuid
import pyotp
from django.utils import timezone
from otp_auth.models import TotpCredential
from passkeys.models import PasskeyCredential
from vaults.models import Vault


def onboarding_session(client, user):
    session = client.session
    session['nimbus_access'] = user.pk
    session['onboarding'] = {'user_id': user.pk, 'started_at': timezone.now().timestamp()}
    session.save()


def factors(user, *, vault=None):
    user.telegram_user_id = user.pk + 10000
    user.save(update_fields=['telegram_user_id'])
    TotpCredential.objects.get_or_create(user=user, defaults={'secret': pyotp.random_base32()})
    if vault is not None:
        PasskeyCredential.objects.get_or_create(user=user, active=True, defaults={
            'credential_id': str(uuid.uuid4()), 'public_key': b'test-only', 'vault': vault,
            'wrapped_key': vault.wrapped_key, 'backup_eligible': True, 'backed_up': True,
        })


def completed_account(client, user):
    vault = Vault.objects.filter(owner=user, revoked_at__isnull=True).first()
    if vault is None:
        vault = Vault.objects.create(owner=user, wrapped_key={})
    factors(user, vault=vault)
    onboarding_session(client, user)
