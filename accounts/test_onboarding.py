import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pyotp
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import TelegramLinkAttempt
from accounts.telegram import handle_update
from accounts.test_support import onboarding_session, factors
from opaque_auth.models import OpaqueCredential
from otp_auth.models import TotpCredential
from passkeys.models import PasskeyIdentity
from passkeys.tests import Authenticator, encrypted
from vaults.models import Vault, CipherFile


@override_settings(TELEGRAM_ENABLED=True, TELEGRAM_BOT_TOKEN='test-token', TELEGRAM_BOT_USERNAME='test_bot', PASSKEY_RP_ID='testserver', PASSKEY_ORIGIN='https://testserver')
class OnboardingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='onboarding', password=None)
        OpaqueCredential.objects.create(user=self.user, registration_record='fixture')
        self.client.force_login(self.user)
        onboarding_session(self.client, self.user)
        session = self.client.session
        session.pop('nimbus_access', None)
        session['opaque_recent_auth'] = {'user_id': self.user.pk, 'credential_version': 1, 'authenticated_at': timezone.now().timestamp()}
        session.save()

    def post(self, path, body=None):
        return self.client.post(path, body or {}, content_type='application/json')

    def status(self):
        return self.client.get('/api/cypher/session/').json()

    def tg_update(self, **data):
        return {'message': {'chat': {'id': 12345, 'type': 'private'}, 'from': {'id': 12345}, **data}}

    def token(self):
        response = self.post('/auth/telegram/link/')
        self.assertEqual(response.status_code, 200, response.content)
        return parse_qs(urlparse(response.json()['url']).query)['start'][0]

    @patch('accounts.telegram.send_message')
    def test_order_and_mandatory_gates_then_real_passkey_and_totp(self, send):
        self.assertEqual(self.status()['next_step'], 'telegram')
        for path in ['/api/cypher/vault/', '/api/passkeys/register/start/', '/api/otp/setup/start/', '/api/cypher/files/', '/auth/settings/']:
            self.assertEqual(self.post(path).status_code, 403, path)
        token = self.token()
        self.assertTrue(handle_update(self.tg_update(text='/start ' + token)))
        self.assertTrue(handle_update(self.tg_update(contact={'user_id': 12345})))
        self.assertFalse(handle_update(self.tg_update(contact={'user_id': 12345})))
        self.assertEqual(self.status()['next_step'], 'passkey')
        self.assertEqual(self.post('/api/otp/setup/start/').status_code, 403)
        vault_id = str(uuid.uuid4())
        self.assertEqual(self.post('/api/cypher/vault/', {'id': vault_id, 'version': 1, 'wrapped_key': encrypted()}).status_code, 201)
        auth = Authenticator()
        start = self.post('/api/passkeys/register/start/').json()
        finish = self.post('/api/passkeys/register/finish/', {'challenge': start['challenge'], 'credential': auth.register(start)})
        self.assertEqual(finish.status_code, 201)
        activate = self.post('/api/passkeys/activate/start/', {'credential_id': finish.json()['id']}).json()
        handle = bytes(PasskeyIdentity.objects.get(user=self.user).user_handle)
        proof = auth.assertion(activate, handle)
        self.assertEqual(self.post('/api/passkeys/activate/finish/', {'challenge': activate['challenge'], 'credential': proof, 'vault_id': vault_id, 'wrapped_key': encrypted()}).status_code, 200)
        self.assertEqual(self.status()['next_step'], 'totp')
        self.assertEqual(self.client.get('/api/cypher/files/').status_code, 403)
        self.assertFalse(self.status()['upload_ready'])
        setup = self.post('/api/otp/setup/start/').json()
        self.assertEqual(self.post('/api/otp/setup/finish/', {'challenge': setup['challenge'], 'code': pyotp.TOTP(setup['secret']).now()}).status_code, 200)
        self.assertFalse(self.status()['onboarding_required'])
        self.assertTrue(self.status()['upload_ready'])
        self.assertEqual(self.client.get('/api/cypher/files/').json(), {'files': []})
        self.assertEqual(self.user.email, '')

    @patch('accounts.telegram.send_message')
    def test_telegram_token_replacement_expiry_and_first_sender_binding(self, send):
        old, fresh = self.token(), self.token()
        self.assertFalse(handle_update(self.tg_update(text='/start ' + old)))
        self.assertTrue(handle_update(self.tg_update(text='/start ' + fresh)))
        stolen = self.tg_update(text='/start ' + fresh)
        stolen['message']['from']['id'] = 555
        stolen['message']['chat']['id'] = 555
        self.assertFalse(handle_update(stolen))
        self.assertFalse(handle_update(self.tg_update(contact={'user_id': 555})))
        TelegramLinkAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(handle_update(self.tg_update(contact={'user_id': 12345})))
        self.user.refresh_from_db()
        self.assertIsNone(self.user.telegram_user_id)

    @patch('accounts.telegram.send_message')
    def test_telegram_identity_cannot_be_claimed_by_second_account(self, send):
        get_user_model().objects.create_user(username='existing', telegram_user_id=12345)
        token = self.token()
        self.assertTrue(handle_update(self.tg_update(text='/start ' + token)))
        self.assertFalse(handle_update(self.tg_update(contact={'user_id': 12345})))
        self.user.refresh_from_db()
        self.assertIsNone(self.user.telegram_user_id)

    def test_session_expiry_and_other_user_marker_do_not_allow_onboarding(self):
        for marker in ({'user_id': self.user.pk, 'started_at': timezone.now().timestamp() - 901}, {'user_id': self.user.pk + 1, 'started_at': timezone.now().timestamp()}):
            session = self.client.session
            session['onboarding'] = marker
            session.save()
            self.assertEqual(self.post('/auth/telegram/link/').status_code, 401)
            self.assertEqual(self.client.get('/api/cypher/files/').status_code, 401)

    @override_settings(TELEGRAM_ENABLED=False, PASSKEY_REQUIRED=False, LOGIN_SECOND_FACTOR_REQUIRED=False)
    def test_disabled_flags_never_unlock_incomplete_accounts(self):
        self.assertEqual(self.post('/auth/telegram/link/').status_code, 503)
        self.assertEqual(self.client.get('/api/cypher/files/').status_code, 403)
        self.assertEqual(self.post('/api/otp/setup/start/').status_code, 403)

    @override_settings(PASSKEY_REQUIRED=False)
    def test_upload_checks_totp_again_after_storage_write(self):
        import tempfile
        from django.core.files.storage import default_storage
        vault = Vault.objects.create(owner=self.user, wrapped_key=encrypted())
        factors(self.user, vault=vault)
        session = self.client.session
        session["nimbus_access"] = self.user.pk
        session.save()
        original = default_storage.save
        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            TotpCredential.objects.filter(user=self.user).delete()
            return result
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory), patch.object(default_storage, 'save', side_effect=revoke), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/api/cypher/files/', {'vault_id': str(vault.pk), 'id': str(uuid.uuid4()), 'metadata': json.dumps(encrypted()), 'file': SimpleUploadedFile('cipher.bin', b'x' * 32)})
            self.assertEqual(response.status_code, 403)
        self.assertFalse(CipherFile.objects.exists())

    def test_another_session_finishing_onboarding_does_not_upgrade_password_only_session(self):
        # Account-level setup can change while an older, password-only session exists.
        vault = Vault.objects.create(owner=self.user, wrapped_key=encrypted())
        factors(self.user, vault=vault)
        self.assertEqual(self.client.get('/api/cypher/files/').status_code, 401)
        self.assertFalse(self.status()['authenticated'])
        self.assertNotIn('_auth_user_id', self.client.session)
