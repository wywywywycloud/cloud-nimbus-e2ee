import pyotp
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from vaults.models import Vault
from otp_auth.models import TotpCredential
from accounts.test_support import factors, onboarding_session

from .models import OpaqueChallenge, OpaqueCredential
from .protocol import call_opaque


NODE_FALLBACK = "node"
CLIENT_SCRIPT = """
import {pathToFileURL} from 'node:url';
const opaque = await import(pathToFileURL(process.env.OPAQUE_MODULE_PATH).href);
await opaque.ready;
let source = '';
for await (const chunk of process.stdin) source += chunk;
const {action, params} = JSON.parse(source);
const result = opaque.client[action](params);
process.stdout.write(JSON.stringify(result ?? null));
"""


def client_call(action, **params):
    result = subprocess.run(
        [settings.OPAQUE_NODE, "--input-type=module", "-e", CLIENT_SCRIPT],
        input=json.dumps({"action": action, "params": params}).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"OPAQUE_MODULE_PATH": str(settings.OPAQUE_MODULE_PATH)},
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def identifiers(username):
    return {"client": username, "server": "cloud-cypher-v1"}


def wrapper(marker):
    def encoded(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")
    return {"v": 1, "iv": encoded(bytes([marker]) * 12), "ct": encoded(bytes([marker]) * 48)}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", OPAQUE_ENABLED=True, LOGIN_SECOND_FACTOR_REQUIRED=False)
class OpaqueAuthTests(TestCase):
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

    def post(self, path, payload, *, client=None):
        return (client or self.client).post(f"/api/opaque/{path}/", payload, content_type="application/json")

    def record(self, username="alice", password="correct horse battery staple"):
        start = client_call("startRegistration", password=password)
        response = call_opaque("createRegistrationResponse", userIdentifier=username, registrationRequest=start["registrationRequest"])
        result = client_call("finishRegistration", password=password, clientRegistrationState=start["clientRegistrationState"], registrationResponse=response["registrationResponse"], identifiers=identifiers(username), keyStretching="memory-constrained")
        return result["registrationRecord"]

    def user(self, username="alice", password="correct horse battery staple"):
        user = get_user_model().objects.create_user(username=username, email=f"{username}@example.test", password=None, email_verified=True)
        OpaqueCredential.objects.create(user=user, registration_record=self.record(username, password))
        return user

    def login_exchange(self, username="alice", password="correct horse battery staple", *, client=None):
        start = client_call("startLogin", password=password)
        response = self.post("login/start", {"username": username, "startLoginRequest": start["startLoginRequest"]}, client=client)
        self.assertEqual(response.status_code, 200)
        result = client_call("finishLogin", password=password, clientLoginState=start["clientLoginState"], loginResponse=response.json()["loginResponse"], identifiers=identifiers(response.json()["username"]), keyStretching="memory-constrained")
        return response.json()["challenge"], result

    def authenticated_client(self, user=None, *, client=None):
        if user is None:
            user = self.user()
        challenge, result = self.login_exchange(user.username, client=client)
        self.assertIsNotNone(result)
        response = self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]}, client=client)
        self.assertEqual(response.status_code, 200)
        return user

    def change_exchange(self, password="new correct horse password", *, client=None):
        start = client_call("startRegistration", password=password)
        response = self.post("change/start", {"registrationRequest": start["registrationRequest"]}, client=client)
        self.assertEqual(response.status_code, 200)
        result = client_call("finishRegistration", password=password, clientRegistrationState=start["clientRegistrationState"], registrationResponse=response.json()["registrationResponse"], identifiers=identifiers("alice"), keyStretching="memory-constrained")
        return {"challenge": response.json()["challenge"], "registrationRecord": result["registrationRecord"]}

    def test_registration_creates_unusable_password_and_starts_telegram_onboarding(self):
        password = "private password sent only to OPAQUE client"
        start = client_call("startRegistration", password=password)
        response = self.post("register/start", {"username": "  Alice  ", "registrationRequest": start["registrationRequest"]})
        self.assertEqual(response.status_code, 200)
        result = client_call("finishRegistration", password=password, clientRegistrationState=start["clientRegistrationState"], registrationResponse=response.json()["registrationResponse"], identifiers=identifiers("alice"), keyStretching="memory-constrained")
        finished = self.post("register/finish", {"challenge": response.json()["challenge"], "registrationRecord": result["registrationRecord"]})
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json()["next_step"], "telegram")
        user = get_user_model().objects.get(username="alice")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.is_active)
        self.assertFalse(user.email_verified)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertEqual(user.email, '')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(OpaqueCredential.objects.get(user=user).registration_record, result['registrationRecord'])
        self.assertNotIn(password, json.dumps(list(OpaqueChallenge.objects.values('payload'))))
        self.assertEqual(self.client.get('/api/cypher/files/').status_code, 403)

    def test_real_login_requires_final_proof_and_consumes_state(self):
        user = self.user()
        challenge, result = self.login_exchange("alice")
        self.assertNotIn("_auth_user_id", self.client.session)
        stored = OpaqueChallenge.objects.get(pk=challenge)
        self.assertIn("server_login_state", stored.payload)
        self.assertNotIn("server_login_state", dict(self.client.session))
        response = self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]})
        self.assertEqual(response.json()["next_step"], "telegram")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertIn("no-store", response["Cache-Control"])
        stored.refresh_from_db()
        self.assertEqual(stored.payload, {})
        self.assertIsNotNone(stored.consumed_at)
        self.assertEqual(self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]}).status_code, 401)

    def test_wrong_password_and_unknown_user_are_indistinguishable_failures(self):
        self.user()
        challenge, result = self.login_exchange("alice", "wrong password")
        self.assertIsNone(result)
        wrong = self.post("login/finish", {"challenge": challenge, "finishLoginRequest": "A" * 64})
        self.assertEqual(wrong.status_code, 401)
        unknown_challenge, result = self.login_exchange("unknown", "wrong password")
        self.assertIsNone(result)
        unknown = self.post("login/finish", {"challenge": unknown_challenge, "finishLoginRequest": "A" * 64})
        self.assertEqual(wrong.json(), unknown.json())
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(OpaqueChallenge.objects.filter(consumed_at__isnull=False).count(), 2)

    def test_bad_proof_consumes_even_when_correct_proof_follows(self):
        self.user()
        challenge, result = self.login_exchange()
        self.assertEqual(self.post("login/finish", {"challenge": challenge, "finishLoginRequest": "not-a-valid-proof"}).status_code, 401)
        self.assertEqual(self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]}).status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_expired_and_wrong_session_proofs_are_rejected(self):
        self.user()
        challenge, result = self.login_exchange()
        proof = {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]}
        other = Client()
        self.assertEqual(self.post("login/finish", proof, client=other).status_code, 401)
        OpaqueChallenge.objects.filter(pk=challenge).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post("login/finish", proof).status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_credential_replacement_invalidates_inflight_login_proof(self):
        user = self.user()
        challenge, result = self.login_exchange()
        credential = user.opaque_credential
        credential.version += 1
        credential.save(update_fields=["version"])
        response = self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_change_requires_recent_opaque_and_invalidates_other_sessions(self):
        user = self.authenticated_client()
        other = Client()
        self.authenticated_client(user, client=other)
        old_django_hash = user.password
        payload = self.change_exchange()
        self.assertEqual(self.post("change/finish", payload).status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())
        self.assertNotEqual(user.password, old_django_hash)
        self.assertEqual(user.opaque_credential.version, 2)
        self.assertTrue(self.client.get("/api/cypher/session/").json()["authenticated"])
        self.assertFalse(other.get("/api/cypher/session/").json()["authenticated"])
        self.client.logout()
        _, old_result = self.login_exchange(password="correct horse battery staple")
        self.assertIsNone(old_result)
        challenge, result = self.login_exchange(password="new correct horse password")
        self.assertIsNotNone(result)
        self.assertEqual(self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]}).status_code, 200)

    def test_password_change_and_vault_wrapper_are_atomic(self):
        user = self.authenticated_client()
        vault = Vault.objects.create(owner=user, wrapped_key=wrapper(1))
        payload = self.change_exchange()
        self.assertEqual(self.post("change/finish", payload).json()["error"], "vault_rewrap_required")
        user.opaque_credential.refresh_from_db()
        self.assertEqual(user.opaque_credential.version, 1)
        payload = self.change_exchange()
        payload.update(vault_id=str(vault.pk), wrapped_key=wrapper(2))
        self.assertEqual(self.post("change/finish", payload).status_code, 200)
        vault.refresh_from_db()
        user.opaque_credential.refresh_from_db()
        self.assertEqual(vault.wrapped_key, wrapper(2))
        self.assertEqual(user.opaque_credential.version, 2)

    def test_vault_changed_mid_password_exchange_rejects_record_update(self):
        user = self.authenticated_client()
        old = Vault.objects.create(owner=user, wrapped_key=wrapper(1))
        payload = self.change_exchange()
        payload.update(vault_id=str(old.pk), wrapped_key=wrapper(2))
        old.revoked_at = timezone.now()
        old.save(update_fields=["revoked_at"])
        current = Vault.objects.create(owner=user, wrapped_key=wrapper(3))
        self.assertEqual(self.post("change/finish", payload).json()["error"], "vault_changed")
        user.opaque_credential.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(user.opaque_credential.version, 1)
        self.assertEqual(current.wrapped_key, wrapper(3))

    def test_expired_recent_auth_and_regular_django_login_cannot_change_opaque(self):
        user = self.user()
        self.client.force_login(user)
        onboarding_session(self.client, user)
        self.assertEqual(self.post("change/start", {"registrationRequest": "A" * 64}).status_code, 403)
        self.authenticated_client(user)
        session = self.client.session
        marker = session["opaque_recent_auth"]
        marker["authenticated_at"] -= 301
        session["opaque_recent_auth"] = marker
        session.save()
        self.assertEqual(self.post("change/start", {"registrationRequest": "A" * 64}).status_code, 403)

    def test_registration_challenge_is_bound_and_record_must_parse(self):
        start = client_call("startRegistration", password="local client only")
        response = self.post("register/start", {"username": "alice", "registrationRequest": start["registrationRequest"]})
        challenge = response.json()["challenge"]
        self.assertEqual(self.post("register/finish", {"challenge": challenge, "registrationRecord": "A" * 192}, client=Client()).status_code, 401)
        self.assertEqual(self.post("register/finish", {"challenge": challenge, "registrationRecord": "A" * 192}).status_code, 400)
        self.assertFalse(get_user_model().objects.filter(username="alice").exists())

    def test_csrf_missing_setup_request_bounds_and_rate_limits(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post("login/start", {}, client=csrf_client).status_code, 403)
        token = csrf_client.get("/api/cypher/session/").json()["csrf_token"]
        response = csrf_client.post("/api/opaque/login/start/", {"username": "alice", "startLoginRequest": "A" * 64}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(self.post("login/start", {"username": "alice", "startLoginRequest": "A" * 9000}).status_code, 400)
        self.assertEqual(self.post("login/start", {"username": "alice", "startLoginRequest": "A" * 64, "password": "must not be accepted"}).status_code, 400)
        with override_settings(OPAQUE_SERVER_SETUP=""):
            self.assertEqual(self.post("login/start", {"username": "alice", "startLoginRequest": "A" * 64}).status_code, 503)
        with patch("opaque_auth.views.allow_action", return_value=False):
            self.assertEqual(self.post("login/start", {"username": "alice", "startLoginRequest": "A" * 64}).status_code, 429)

    def test_setup_generation_is_private_and_never_overwrites(self):
        from django.core.management.base import CommandError
        import io
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private.env"
            stdout = io.StringIO()
            call_command("generate_opaque_setup", output=str(output), stdout=stdout)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertTrue(output.read_text().startswith("OPAQUE_SERVER_SETUP="))
            self.assertNotIn(output.read_text().strip(), stdout.getvalue())
            before = output.read_bytes()
            with self.assertRaises(CommandError):
                call_command("generate_opaque_setup", output=str(output), stdout=stdout)
            self.assertEqual(output.read_bytes(), before)

    def test_cleanup_removes_expired_and_consumed_exchange_secrets(self):
        import io
        self.user()
        challenge, _ = self.login_exchange()
        OpaqueChallenge.objects.filter(pk=challenge).update(expires_at=timezone.now() - timedelta(seconds=1))
        call_command("cleanup_opaque_challenges", stdout=io.StringIO())
        self.assertFalse(OpaqueChallenge.objects.exists())

    def test_email_login_is_rejected(self):
        self.user()
        response = self.post('login/start', {'username': 'alice@example.test', 'startLoginRequest': 'A' * 64})
        self.assertEqual(response.status_code, 400)

    def test_verified_passkey_can_add_first_password_and_rewrap_current_vault(self):
        user = get_user_model().objects.create_user(username="alice", email="alice@example.test", password=None, email_verified=True)
        self.client.force_login(user)
        onboarding_session(self.client, user)
        session = self.client.session
        session["passkey_recent_auth"] = {"user_id": user.pk, "authenticated_at": timezone.now().timestamp()}
        session.save()
        vault = Vault.objects.create(owner=user, wrapped_key=wrapper(1))
        payload = self.change_exchange()
        payload.update(vault_id=str(vault.pk), wrapped_key=wrapper(2))
        self.assertEqual(self.post("change/finish", payload).status_code, 200)
        self.assertEqual(OpaqueCredential.objects.get(user=user).version, 1)
        vault.refresh_from_db()
        self.assertEqual(vault.wrapped_key, wrapper(2))
        self.client.logout()
        challenge, result = self.login_exchange(password="new correct horse password")
        self.assertIsNotNone(result)
        self.assertEqual(self.post("login/finish", {"challenge": challenge, "finishLoginRequest": result["finishLoginRequest"]}).status_code, 200)

    def test_telegram_reset_marker_never_changes_password_while_vault_exists(self):
        user = self.user()
        self.client.force_login(user)
        onboarding_session(self.client, user)
        session = self.client.session
        session["passkey_recent_reset"] = {"user_id": user.pk, "authenticated_at": timezone.now().timestamp()}
        session.save()
        vault = Vault.objects.create(owner=user, wrapped_key=wrapper(1))
        self.assertEqual(self.post("change/start", {"registrationRequest": "A" * 64}).status_code, 403)
        vault.revoked_at = timezone.now()
        vault.save(update_fields=["revoked_at"])
        payload = self.change_exchange()
        self.assertEqual(self.post("change/finish", payload).status_code, 200)
        self.assertEqual(OpaqueCredential.objects.get(user=user).version, 2)
