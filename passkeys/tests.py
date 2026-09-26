import base64
import hashlib
import json
import re
import secrets
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from opaque_auth.models import OpaqueCredential
from otp_auth.models import OtpChallenge, TotpCredential
from vaults.models import BlobDeletion, CipherFile, Vault

from .models import PasskeyChallenge, PasskeyCredential, PasskeyIdentity, PasskeyReset
from .views import PRF_SALT


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def encrypted(size=48):
    return {"v": 1, "iv": b64(b"i" * 12), "ct": b64(b"x" * size)}


class Authenticator:
    """Real P-256 signatures and canonical WebAuthn CBOR, without verifier mocks."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        numbers = self.key.public_key().public_numbers()
        self.cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32), -3: numbers.y.to_bytes(32)})

    def _client_data(self, options, kind, origin, **extra):
        return json.dumps({"type": kind, "challenge": options["publicKey"]["challenge"], "origin": origin, "crossOrigin": False, **extra}, separators=(",", ":")).encode()

    def register(self, options, *, origin="https://testserver", flags=0x5D):
        client_data = self._client_data(options, "webauthn.create", origin)
        auth_data = hashlib.sha256(b"testserver").digest() + bytes([flags]) + bytes(4) + bytes(16) + len(self.id).to_bytes(2) + self.id + self.cose
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "response": {"clientDataJSON": b64(client_data), "attestationObject": b64(cbor2.dumps({"fmt": "none", "authData": auth_data, "attStmt": {}}))}, "clientExtensionResults": {"prf": {"enabled": True}}}

    def assertion(self, options, handle, *, origin="https://testserver", flags=0x1D, count=0, **extra):
        client_data = self._client_data(options, "webauthn.get", origin, **extra)
        auth_data = hashlib.sha256(b"testserver").digest() + bytes([flags]) + count.to_bytes(4)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data), "signature": b64(signature), "userHandle": b64(handle) if handle is not None else None}}


@override_settings(PASSKEY_RP_ID="testserver", PASSKEY_ORIGIN="https://testserver", PASSKEY_REQUIRED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasskeyTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user(username="owner", email="owner@example.test", password=None, email_verified=True)
        OpaqueCredential.objects.create(user=self.user, registration_record="opaque-record")
        self.vault = Vault.objects.create(owner=self.user, wrapped_key=encrypted())
        self.client.force_login(self.user)
        session = self.client.session
        session["opaque_recent_auth"] = {"user_id": self.user.pk, "credential_version": 1, "authenticated_at": timezone.now().timestamp()}
        session.save()
        self.authenticator = Authenticator()

    def post(self, route, payload, *, client=None):
        return (client or self.client).post(f"/api/passkeys/{route}/", payload, content_type="application/json")

    def register(self):
        start = self.post("register/start", {})
        self.assertEqual(start.status_code, 200, start.content)
        finish = self.post("register/finish", {"challenge": start.json()["challenge"], "credential": self.authenticator.register(start.json())})
        self.assertEqual(finish.status_code, 201, finish.content)
        return finish.json()["id"]

    def activate(self):
        credential_id = self.register()
        options = self.post("activate/start", {"credential_id": credential_id}).json()
        response = self.post("activate/finish", {"challenge": options["challenge"], "credential": self.assertion(options), "vault_id": str(self.vault.pk), "wrapped_key": encrypted()})
        self.assertEqual(response.status_code, 200, response.content)
        return PasskeyCredential.objects.get(credential_id=credential_id)

    def assertion(self, options, **kwargs):
        return self.authenticator.assertion(options, bytes(PasskeyIdentity.objects.get(user=self.user).user_handle), **kwargs)

    def login(self, client=None, **kwargs):
        client = client or Client()
        options = self.post("login/start", {}, client=client).json()
        response = self.post("login/finish", {"challenge": options["challenge"], "credential": self.assertion(options, **kwargs)}, client=client)
        return response, client

    def reset_start(self, client=None):
        response = self.post("reset/start", {"email": self.user.email}, client=client)
        self.assertEqual(response.status_code, 200)
        return response.json()["challenge"], re.search(r"Код: ([0-9]{6})", mail.outbox[-1].body).group(1)

    def reset_finish(self, identifier, code, client=None):
        return self.post("reset/finish", {"challenge": identifier, "code": code, "confirmation": "DELETE ALL FILES"}, client=client)

    def upload(self):
        return self.client.post("/api/cypher/files/", {"vault_id": str(self.vault.pk), "id": str(uuid.uuid4()), "metadata": json.dumps(encrypted(32)), "file": SimpleUploadedFile("encrypted.bin", b"ciphertext-only!!")})

    def test_create_get_login_uses_real_signatures_and_synced_zero_counters(self):
        credential = self.activate()
        self.assertTrue(credential.active)
        self.assertTrue(credential.backup_eligible)
        response, client = self.login()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"username": "owner", "vault": {"id": str(self.vault.pk), "version": 1, "wrapped_key": encrypted()}})
        self.assertIn("passkey_recent_auth", client.session)
        response, _ = self.login()
        self.assertEqual(response.status_code, 200)

    def test_creation_options_require_resident_uv_and_stable_prf_salt(self):
        options = self.post("register/start", {}).json()["publicKey"]
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "required")
        self.assertEqual(options["extensions"], {"prf": {"eval": {"first": b64(PRF_SALT)}}})
        self.assertEqual(len(base64.urlsafe_b64decode(options["user"]["id"] + "=")), 32)

    def test_recent_opaque_version_and_authenticated_user_required(self):
        self.assertEqual(self.post("register/start", {}, client=Client()).status_code, 401)
        OpaqueCredential.objects.filter(user=self.user).update(version=2)
        self.assertEqual(self.post("register/start", {}).status_code, 401)

    def test_existing_active_passkey_cannot_be_replaced(self):
        self.activate()
        self.assertEqual(self.post("register/start", {}).status_code, 409)

    def test_registration_rejects_wrong_origin(self):
        options = self.post("register/start", {}).json()
        response = self.post("register/finish", {"challenge": options["challenge"], "credential": self.authenticator.register(options, origin="https://attacker.test")})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(PasskeyCredential.objects.exists())

    def test_registration_requires_uv_and_backup_eligibility(self):
        for flags, expected in ((0x59, 401), (0x45, 400)):
            options = self.post("register/start", {}).json()
            response = self.post("register/finish", {"challenge": options["challenge"], "credential": self.authenticator.register(options, flags=flags)})
            self.assertEqual(response.status_code, expected, response.content)

    def test_prf_results_never_accepted_by_backend(self):
        options = self.post("register/start", {}).json()
        credential = self.authenticator.register(options)
        credential["clientExtensionResults"]["prf"]["results"] = {"first": b64(b"private" * 6)}
        self.assertEqual(self.post("register/finish", {"challenge": options["challenge"], "credential": credential}).status_code, 401)
        self.assertFalse(PasskeyCredential.objects.exists())

    def test_pending_credential_cannot_login_or_upload(self):
        self.register()
        self.assertEqual(self.login()[0].status_code, 401)
        self.assertEqual(self.upload().json(), {"error": "passkey_required"})
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(BlobDeletion.objects.exists())

    def test_activation_rejects_foreign_vault_and_does_not_activate(self):
        credential_id = self.register()
        other = get_user_model().objects.create_user(username="other", email="other@example.test", email_verified=True)
        foreign_vault = Vault.objects.create(owner=other, wrapped_key=encrypted())
        options = self.post("activate/start", {"credential_id": credential_id}).json()
        response = self.post("activate/finish", {"challenge": options["challenge"], "credential": self.assertion(options), "vault_id": str(foreign_vault.pk), "wrapped_key": encrypted()})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(PasskeyCredential.objects.get(credential_id=credential_id).active)

    def test_activation_requires_signed_backup_state_not_just_eligibility(self):
        options = self.post("register/start", {}).json()
        registration = self.post("register/finish", {"challenge": options["challenge"], "credential": self.authenticator.register(options, flags=0x4D)})
        self.assertEqual(registration.status_code, 201)
        credential_id = registration.json()["id"]
        options = self.post("activate/start", {"credential_id": credential_id}).json()
        response = self.post("activate/finish", {"challenge": options["challenge"], "credential": self.assertion(options, flags=0x0D), "vault_id": str(self.vault.pk), "wrapped_key": encrypted()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "passkey_backup_required"})
        credential = PasskeyCredential.objects.get(credential_id=credential_id)
        self.assertTrue(credential.backup_eligible)
        self.assertFalse(credential.backed_up)
        self.assertFalse(credential.active)
        self.assertEqual(self.upload().json(), {"error": "passkey_required"})

    def test_loss_of_backup_state_allows_reading_but_blocks_uploads(self):
        self.activate()
        self.assertEqual(self.upload().status_code, 201)
        item = CipherFile.objects.get()
        response, client = self.login(flags=0x0D)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(client.get("/api/cypher/session/").json()["passkey_ready"])
        self.assertEqual(client.get(f"/api/cypher/files/{item.pk}/download/").status_code, 200)
        self.assertEqual(self.upload().json(), {"error": "passkey_required"})
        self.assertEqual(self.login()[0].status_code, 200)
        self.assertTrue(self.client.get("/api/cypher/session/").json()["passkey_ready"])

    def test_upload_rechecks_passkey_under_publication_lock(self):
        credential = self.activate()
        original_save = default_storage.save

        def disable_during_storage_save(*args, **kwargs):
            result = original_save(*args, **kwargs)
            PasskeyCredential.objects.filter(pk=credential.pk).update(active=False)
            return result

        with patch.object(default_storage, "save", side_effect=disable_during_storage_save), self.captureOnCommitCallbacks(execute=True):
            response = self.upload()
        self.assertEqual(response.json(), {"error": "passkey_required"})
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(BlobDeletion.objects.exists())

    def test_upload_ready_only_for_current_vault_and_reset_clears_credential(self):
        self.assertFalse(self.client.get("/api/cypher/session/").json()["passkey_ready"])
        self.activate()
        data = self.client.get("/api/cypher/session/").json()
        self.assertTrue(data["passkey_ready"])
        self.assertEqual(data["user"]["email"], self.user.email)
        self.assertEqual(self.upload().status_code, 201)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/cypher/reset/", {"vault_id": str(self.vault.pk), "confirmation": "DELETE"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PasskeyCredential.objects.exists())

    def test_assertion_rejects_origin_uv_signature_crossorigin_and_user_handle(self):
        self.activate()
        for kwargs in ({"origin": "https://attacker.test"}, {"flags": 0x19}, {"crossOrigin": True}):
            self.assertEqual(self.login(**kwargs)[0].status_code, 401)
        for field, value in (("signature", b64(b"bad-signature")), ("userHandle", b64(b"wrong-user"))):
            options = self.post("login/start", {}).json()
            credential = self.assertion(options)
            credential["response"][field] = value
            self.assertEqual(self.post("login/finish", {"challenge": options["challenge"], "credential": credential}).status_code, 401)

    def test_replay_expiration_and_session_binding(self):
        self.activate()
        options = self.post("login/start", {}).json()
        payload = {"challenge": options["challenge"], "credential": self.assertion(options)}
        self.assertEqual(self.post("login/finish", payload, client=Client()).status_code, 401)
        self.assertEqual(self.post("login/finish", payload).status_code, 200)
        self.assertEqual(self.post("login/finish", payload).status_code, 401)
        options = self.post("login/start", {}).json()
        PasskeyChallenge.objects.filter(pk=options["challenge"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post("login/finish", {"challenge": options["challenge"], "credential": self.assertion(options)}).status_code, 401)

    def test_wrong_challenge_is_consumed_even_with_valid_signature(self):
        self.activate()
        options = self.post("login/start", {}).json()
        changed = json.loads(json.dumps(options))
        changed["publicKey"]["challenge"] = b64(secrets.token_bytes(32))
        self.assertEqual(self.post("login/finish", {"challenge": options["challenge"], "credential": self.assertion(changed)}).status_code, 401)
        self.assertEqual(self.post("login/finish", {"challenge": options["challenge"], "credential": self.assertion(options)}).status_code, 401)

    def test_sign_counter_replay_is_rejected(self):
        self.activate()
        self.assertEqual(self.login(count=2)[0].status_code, 200)
        self.assertEqual(self.login(count=2)[0].status_code, 401)
        self.assertEqual(self.login(count=3)[0].status_code, 200)

    def test_email_selected_login_cannot_use_another_account(self):
        self.activate()
        options = self.post("login/start", {"email": "unknown@example.test"}).json()
        self.assertEqual(self.post("login/finish", {"challenge": options["challenge"], "credential": self.assertion(options)}).status_code, 401)
        options = self.post("login/start", {"email": self.user.email}).json()
        self.assertEqual(self.post("login/finish", {"challenge": options["challenge"], "credential": self.assertion(options)}).status_code, 200)

    def test_email_reset_wipes_ciphertext_revokes_sessions_and_keeps_opaque_record(self):
        self.activate()
        TotpCredential.objects.create(user=self.user, secret="A" * 32)
        OtpChallenge.objects.create(user=self.user, kind="setup", method="totp", session_digest="x" * 64, payload={"secret": "A" * 32}, expires_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(self.upload().status_code, 201)
        storage_key = CipherFile.objects.get().storage_key
        old_client = Client()
        old_client.force_login(self.user)
        anonymous = Client()
        identifier, code = self.reset_start(anonymous)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.reset_finish(identifier, code, anonymous)
        self.assertEqual(response.status_code, 200, response.content)
        self.vault.refresh_from_db()
        self.user.refresh_from_db()
        self.assertIsNotNone(self.vault.revoked_at)
        self.assertEqual(self.vault.wrapped_key, {})
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(default_storage.exists(storage_key))
        self.assertFalse(PasskeyCredential.objects.exists())
        self.assertFalse(TotpCredential.objects.exists())
        self.assertFalse(OtpChallenge.objects.exists())
        self.assertEqual(self.user.used_bytes, 0)
        self.assertTrue(OpaqueCredential.objects.filter(user=self.user, registration_record="opaque-record").exists())
        self.assertFalse(old_client.get("/api/cypher/session/").json()["authenticated"])
        self.assertTrue(anonymous.get("/api/cypher/session/").json()["authenticated"])
        self.assertIn("passkey_recent_reset", anonymous.session)
        self.assertEqual(self.reset_finish(identifier, code, anonymous).status_code, 401)
        response = anonymous.post("/api/cypher/vault/", {"id": str(self.vault.pk), "version": 1, "wrapped_key": encrypted()}, content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_email_reset_requires_exact_confirmation_and_bound_session(self):
        identifier, code = self.reset_start()
        self.assertEqual(self.reset_finish(identifier, code, Client()).status_code, 401)
        self.assertEqual(self.post("reset/finish", {"challenge": identifier, "code": code, "confirmation": "DELETE"}).status_code, 401)
        self.vault.refresh_from_db()
        self.assertIsNone(self.vault.revoked_at)

    def test_email_reset_invalidates_other_pending_reset_and_auth_challenges(self):
        self.activate()
        pending_login = self.post("login/start", {"email": self.user.email}).json()
        pending_assertion = self.assertion(pending_login)
        first_id, first_code = self.reset_start()
        other = Client()
        other_id, other_code = self.reset_start(other)
        self.assertEqual(self.reset_finish(first_id, first_code).status_code, 200)
        self.assertEqual(self.reset_finish(other_id, other_code, other).status_code, 401)
        self.assertEqual(self.post("login/finish", {"challenge": pending_login["challenge"], "credential": pending_assertion}).status_code, 401)

    def test_email_code_max_five_guesses_and_expiration(self):
        identifier, code = self.reset_start()
        wrong = "000000" if code != "000000" else "999999"
        for _ in range(5):
            self.assertEqual(self.reset_finish(identifier, wrong).status_code, 401)
        self.assertEqual(self.reset_finish(identifier, code).status_code, 401)
        self.assertEqual(PasskeyReset.objects.get(pk=identifier).attempts, 5)
        identifier, code = self.reset_start()
        PasskeyReset.objects.filter(pk=identifier).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.reset_finish(identifier, code).status_code, 401)

    def test_unknown_email_is_neutral_and_does_not_send_mail(self):
        mail.outbox = []
        response = self.post("reset/start", {"email": "unknown@example.test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"challenge"})
        self.assertEqual(len(mail.outbox), 0)

    def test_email_reset_limits_and_csrf(self):
        for _ in range(5):
            self.assertEqual(self.post("reset/start", {"email": self.user.email}).status_code, 200)
        self.assertEqual(self.post("reset/start", {"email": self.user.email}).status_code, 429)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post("login/start", {}, client=client).status_code, 403)
        self.assertEqual(self.post("reset/start", {"email": self.user.email}, client=client).status_code, 403)

    def test_revoked_vault_never_authenticates(self):
        self.activate()
        self.vault.revoked_at = timezone.now()
        self.vault.save(update_fields=["revoked_at"])
        self.assertEqual(self.login()[0].status_code, 401)
