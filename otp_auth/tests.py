import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import pyotp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from opaque_auth.models import OpaqueCredential
from opaque_auth.protocol import call_opaque
from opaque_auth.tests import NODE_FALLBACK, client_call, identifiers

from .models import OtpChallenge, TotpCredential


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", OPAQUE_ENABLED=True, LOGIN_SECOND_FACTOR_REQUIRED=True)
class OtpAuthTests(TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = os.environ.get("OPAQUE_NODE") or shutil.which("node") or NODE_FALLBACK
        cls.runtime_settings = override_settings(OPAQUE_NODE=runtime, OPAQUE_MODULE_PATH=settings.BASE_DIR / "cloud-cypher/web/vendor/opaque.js")
        cls.runtime_settings.enable()
        cls.addClassCleanup(cls.runtime_settings.disable)
        cls.setup_settings = override_settings(OPAQUE_SERVER_SETUP=call_opaque("createSetup")["serverSetup"])
        cls.setup_settings.enable()
        cls.addClassCleanup(cls.setup_settings.disable)
        super().setUpClass()

    def setUp(self):
        self.now = datetime(2026, 9, 26, 12, 0, 1, tzinfo=dt_timezone.utc)
        patcher = patch("django.utils.timezone.now", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.password = "correct horse battery staple"
        self.user = get_user_model().objects.create_user(username="alice", email="alice@example.test", password=None, email_verified=True)
        start = client_call("startRegistration", password=self.password)
        registration = call_opaque("createRegistrationResponse", userIdentifier="alice", registrationRequest=start["registrationRequest"])
        result = client_call("finishRegistration", password=self.password, clientRegistrationState=start["clientRegistrationState"], registrationResponse=registration["registrationResponse"], identifiers=identifiers("alice"), keyStretching="memory-constrained")
        self.credential = OpaqueCredential.objects.create(user=self.user, registration_record=result["registrationRecord"])

    def post(self, path, payload, client=None):
        return (client or self.client).post(f"/api/otp/{path}/", payload, content_type="application/json")

    def begin_login(self, client=None):
        client = client or self.client
        start = client_call("startLogin", password=self.password)
        response = client.post("/api/opaque/login/start/", {"username": "alice", "startLoginRequest": start["startLoginRequest"]}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        result = client_call("finishLogin", password=self.password, clientLoginState=start["clientLoginState"], loginResponse=response.json()["loginResponse"], identifiers=identifiers("alice"), keyStretching="memory-constrained")
        finish = client.post("/api/opaque/login/finish/", {"challenge": response.json()["challenge"], "finishLoginRequest": result["finishLoginRequest"]}, content_type="application/json")
        self.assertEqual(finish.status_code, 200, finish.content)
        self.assertTrue(finish.json()["second_factor_required"])
        self.assertIn("exportKey", result)
        self.assertNotIn(result["exportKey"], finish.content.decode())
        self.assertNotIn(result["exportKey"], json.dumps(list(OtpChallenge.objects.values("payload"))))
        return finish.json()

    def finish_login(self, challenge, code, client=None):
        return self.post("login/finish", {"challenge": challenge, "code": code}, client)

    def email_code(self):
        return re.search(r"Код входа: ([0-9]{6})", mail.outbox[-1].body).group(1)

    def recent_login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["opaque_recent_auth"] = {"user_id": self.user.pk, "credential_version": self.credential.version, "authenticated_at": timezone.now().timestamp()}
        session.save()

    def enroll(self):
        self.recent_login()
        start = self.post("setup/start", {})
        self.assertEqual(start.status_code, 200, start.content)
        payload = start.json()
        self.assertIn("otpauth://totp/", payload["otpauth_uri"])
        self.assertIn(self.user.email.replace("@", "%40"), payload["otpauth_uri"])
        response = self.post("setup/finish", {"challenge": payload["challenge"], "code": pyotp.TOTP(payload["secret"]).at(self.now)})
        self.assertEqual(response.status_code, 200, response.content)
        return payload["secret"]

    def test_opaque_proof_does_not_authenticate_until_email_code(self):
        challenge = self.begin_login()
        self.assertEqual(challenge["method"], "email")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(self.client.get("/api/cypher/session/").json()["authenticated"])
        response = self.finish_login(challenge["challenge"], self.email_code())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"username": "alice"})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertEqual(self.client.session["opaque_recent_auth"]["credential_version"], 1)
        stored = OtpChallenge.objects.get(pk=challenge["challenge"])
        self.assertEqual(stored.payload, {})
        self.assertIsNotNone(stored.consumed_at)
        self.assertIn("no-store", response["Cache-Control"])

    def test_email_wrong_attempts_replay_and_session_binding(self):
        challenge = self.begin_login()["challenge"]
        code = self.email_code()
        self.assertEqual(self.finish_login(challenge, code, Client()).status_code, 401)
        wrong = "000000" if code != "000000" else "999999"
        for _ in range(5):
            self.assertEqual(self.finish_login(challenge, wrong).status_code, 401)
        self.assertEqual(self.finish_login(challenge, code).status_code, 401)
        self.assertEqual(OtpChallenge.objects.get(pk=challenge).payload, {})
        self.assertNotIn("_auth_user_id", self.client.session)
        challenge = self.begin_login()["challenge"]
        code = self.email_code()
        self.assertEqual(self.finish_login(challenge, code).status_code, 200)
        self.assertEqual(self.finish_login(challenge, code).status_code, 401)

    def test_expired_and_replaced_credentials_invalidate_email_proof(self):
        challenge = self.begin_login()["challenge"]
        code = self.email_code()
        self.now += timedelta(minutes=6)
        self.assertEqual(self.finish_login(challenge, code).status_code, 401)
        challenge = self.begin_login()["challenge"]
        code = self.email_code()
        OpaqueCredential.objects.filter(pk=self.credential.pk).update(version=2)
        self.assertEqual(self.finish_login(challenge, code).status_code, 401)

    def test_session_hash_rotation_invalidates_inflight_email_proof(self):
        challenge = self.begin_login()["challenge"]
        code = self.email_code()
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        self.assertEqual(self.finish_login(challenge, code).status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_totp_enrollment_requires_recent_auth_and_proof(self):
        self.assertEqual(self.post("setup/start", {}).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.post("setup/start", {}).status_code, 401)
        self.recent_login()
        start = self.post("setup/start", {}).json()
        self.assertFalse(TotpCredential.objects.exists())
        self.assertEqual(self.post("setup/finish", {"challenge": start["challenge"], "code": pyotp.TOTP(start["secret"]).at(self.now)}, Client()).status_code, 401)
        self.assertEqual(self.post("setup/finish", {"challenge": start["challenge"], "code": pyotp.TOTP(start["secret"]).at(self.now)}).status_code, 200)
        self.assertEqual(self.post("setup/start", {}).status_code, 409)
        self.assertEqual(OtpChallenge.objects.get(pk=start["challenge"]).payload, {})

    def test_totp_replaces_email_and_requires_fresh_counter(self):
        secret = self.enroll()
        self.client.logout()
        mail.outbox = []
        challenge = self.begin_login()
        self.assertEqual(challenge["method"], "totp")
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.finish_login(challenge["challenge"], pyotp.TOTP(secret).at(self.now)).status_code, 401)
        self.now += timedelta(seconds=30)
        code = pyotp.TOTP(secret).at(self.now)
        self.assertEqual(self.finish_login(challenge["challenge"], code).status_code, 200)
        self.assertEqual(self.finish_login(challenge["challenge"], code).status_code, 401)
        another = Client()
        next_challenge = self.begin_login(another)
        self.assertEqual(self.finish_login(next_challenge["challenge"], code, another).status_code, 401)
        self.now += timedelta(seconds=30)
        self.assertEqual(self.finish_login(next_challenge["challenge"], pyotp.TOTP(secret).at(self.now), another).status_code, 200)

    def test_totp_never_falls_back_to_email_after_config_removed(self):
        secret = self.enroll()
        self.client.logout()
        challenge = self.begin_login()
        TotpCredential.objects.filter(user=self.user).delete()
        self.now += timedelta(seconds=30)
        self.assertEqual(self.finish_login(challenge["challenge"], pyotp.TOTP(secret).at(self.now)).status_code, 401)

    def test_enrollment_invalidates_preexisting_email_challenge(self):
        old_client = Client()
        old_challenge = self.begin_login(old_client)
        old_code = self.email_code()
        self.enroll()
        self.assertEqual(self.finish_login(old_challenge["challenge"], old_code, old_client).status_code, 401)

    def test_setup_expiration_replacement_and_csrf(self):
        self.recent_login()
        first = self.post("setup/start", {}).json()
        second = self.post("setup/start", {}).json()
        self.assertEqual(self.post("setup/finish", {"challenge": first["challenge"], "code": pyotp.TOTP(first["secret"]).at(self.now)}).status_code, 401)
        self.now += timedelta(minutes=6)
        self.assertEqual(self.post("setup/finish", {"challenge": second["challenge"], "code": pyotp.TOTP(second["secret"]).at(self.now)}).status_code, 401)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post("setup/start", {}, csrf_client).status_code, 403)
        self.assertEqual(self.post("login/finish", {"challenge": second["challenge"], "code": "000000"}, csrf_client).status_code, 403)

    def test_email_failure_never_authenticates_or_leaves_live_secret(self):
        start = client_call("startLogin", password=self.password)
        response = self.client.post("/api/opaque/login/start/", {"username": "alice", "startLoginRequest": start["startLoginRequest"]}, content_type="application/json")
        result = client_call("finishLogin", password=self.password, clientLoginState=start["clientLoginState"], loginResponse=response.json()["loginResponse"], identifiers=identifiers("alice"), keyStretching="memory-constrained")
        with patch("otp_auth.services.send_mail", side_effect=RuntimeError("offline")):
            finish = self.client.post("/api/opaque/login/finish/", {"challenge": response.json()["challenge"], "finishLoginRequest": result["finishLoginRequest"]}, content_type="application/json")
        self.assertEqual(finish.status_code, 503)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(OtpChallenge.objects.filter(consumed_at__isnull=True).exists())

    def test_setup_attempt_limit_rate_limit_and_expired_secret_cleanup(self):
        import io

        self.recent_login()
        setup = self.post("setup/start", {}).json()
        wrong = next(f"{number:06d}" for number in range(100) if all(pyotp.TOTP(setup["secret"]).at(self.now + timedelta(seconds=offset * 30)) != f"{number:06d}" for offset in (-1, 0, 1)))
        for _ in range(5):
            self.assertEqual(self.post("setup/finish", {"challenge": setup["challenge"], "code": wrong}).status_code, 401)
        self.assertEqual(self.post("setup/finish", {"challenge": setup["challenge"], "code": pyotp.TOTP(setup["secret"]).at(self.now)}).status_code, 401)
        self.assertEqual(OtpChallenge.objects.get(pk=setup["challenge"]).payload, {})
        for _ in range(4):
            self.assertEqual(self.post("setup/start", {}).status_code, 200)
        self.assertEqual(self.post("setup/start", {}).status_code, 429)
        self.now += timedelta(minutes=6)
        call_command("cleanup_otp_challenges", stdout=io.StringIO())
        self.assertFalse(OtpChallenge.objects.exists())
