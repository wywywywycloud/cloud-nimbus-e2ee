from datetime import timedelta
from unittest.mock import patch
import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, Client
from django.utils import timezone
from accounts.test_support import completed_account, onboarding_session
from .models import TotpCredential, OtpChallenge


class RotationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username='rotate', password=None)
        self.client.force_login(self.user); completed_account(self.client, self.user)
        self.old = TotpCredential.objects.get(user=self.user)
        self.now = timezone.now()
        timer = patch('django.utils.timezone.now', side_effect=lambda: self.now)
        timer.start(); self.addCleanup(timer.stop)

    def post(self, path, data, client=None):
        return (client or self.client).post('/api/otp/rotate/'+path+'/', data, content_type='application/json')

    def start(self):
        response = self.post('start', {'code': pyotp.TOTP(self.old.secret).at(self.now)})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_two_phase_rotation_preserves_vault_revokes_sessions_and_replay(self):
        other = Client(); other.force_login(self.user); onboarding_session(other, self.user)
        vault = self.user.cipher_vaults.get(); original = vault.wrapped_key
        data = self.start()
        self.assertEqual(TotpCredential.objects.get(user=self.user).secret, self.old.secret)
        proof = {'challenge': data['challenge'], 'code': pyotp.TOTP(data['secret']).at(self.now)}
        self.assertEqual(self.post('finish', proof, other).status_code, 401)
        self.assertEqual(self.post('finish', proof).status_code, 200)
        self.assertEqual(TotpCredential.objects.get(user=self.user).secret, data['secret'])
        self.assertNotEqual(TotpCredential.objects.get(user=self.user).pk, self.old.pk)
        self.assertEqual(self.post('finish', proof).status_code, 401)
        self.assertTrue(self.client.get('/api/cypher/session/').json()['authenticated'])
        self.assertFalse(other.get('/api/cypher/session/').json()['authenticated'])
        vault.refresh_from_db(); self.assertEqual(vault.wrapped_key, original); self.assertIsNone(vault.revoked_at)

    def test_bad_codes_expiry_and_attempt_limit_keep_old_secret(self):
        self.assertEqual(self.post('start', {'code': ''}).status_code, 401)
        data = self.start()
        valid = pyotp.TOTP(data['secret']).at(self.now)
        wrong = next(f'{n:06}' for n in range(1000000) if all(f'{n:06}' != pyotp.TOTP(data['secret']).at(self.now+timedelta(seconds=d)) for d in [-30,0,30]))
        for _ in range(5): self.assertEqual(self.post('finish', {'challenge': data['challenge'], 'code': wrong}).status_code, 401)
        self.assertEqual(self.post('finish', {'challenge': data['challenge'], 'code': valid}).status_code, 401)
        self.now += timedelta(seconds=60); data = self.start(); self.now += timedelta(minutes=6)
        self.assertEqual(self.post('finish', {'challenge': data['challenge'], 'code': pyotp.TOTP(data['secret']).at(self.now)}).status_code, 401)
        self.assertEqual(TotpCredential.objects.get(user=self.user).secret, self.old.secret)

    def test_recent_passkey_and_csrf(self):
        session=self.client.session; session['passkey_recent_auth']={'user_id':self.user.pk,'authenticated_at':self.now.timestamp()}; session.save()
        self.assertEqual(self.post('start', {'code':''}).status_code, 200)
        self.now += timedelta(minutes=6)
        self.assertEqual(self.post('start', {'code':''}).status_code, 401)
        csrf=Client(enforce_csrf_checks=True); csrf.force_login(self.user); onboarding_session(csrf,self.user)
        self.assertEqual(self.post('start', {'code':'123456'}, csrf).status_code, 403)
        self.assertEqual(self.post('start', {'code':'123456'}, Client()).status_code, 401)
