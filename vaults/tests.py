import base64
import io
import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from drive.models import StoredFile

from .models import BlobDeletion, CipherFile, Vault


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def encrypted(size=32):
    return {"v": 1, "iv": b64(b"i" * 12), "ct": b64(b"x" * size)}


@override_settings(PASSKEY_REQUIRED=False)
class VaultAPITests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name, MALWARE_SCAN_REQUIRED=True)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = get_user_model().objects.create_user(username="owner", email="owner@example.test", password="test-password", email_verified=True)
        self.other = get_user_model().objects.create_user(username="other", email="other@example.test", password="test-password", email_verified=True)
        self.client.force_login(self.user)
        self.other_client = Client()
        self.other_client.force_login(self.other)
        self.vault_id = str(uuid.uuid4())

    def create_vault(self, *, vault_id=None, client=None):
        return (client or self.client).post("/api/cypher/vault/", {"id": vault_id or self.vault_id, "version": 1, "wrapped_key": encrypted(48)}, content_type="application/json")

    def upload(self, *, data=b"opaque ciphertext" * 2, metadata=None, file_id=None, vault_id=None, client=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client).post("/api/cypher/files/", {
                "vault_id": vault_id or self.vault_id,
                "id": file_id or str(uuid.uuid4()),
                "metadata": json.dumps(metadata if metadata is not None else encrypted()),
                "file": SimpleUploadedFile("never-use-this-name.txt", data, content_type="application/octet-stream"),
            })

    def reset_vault(self, *, vault_id=None, client=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client).post("/api/cypher/reset/", {"vault_id": vault_id or self.vault_id, "confirmation": "DELETE"}, content_type="application/json")

    def test_public_session_sets_csrf_and_protected_endpoints_return_json_401(self):
        anonymous = Client(enforce_csrf_checks=True)
        session = anonymous.get("/api/cypher/session/")
        self.assertFalse(session.json()["authenticated"])
        self.assertIn("csrftoken", session.cookies)
        self.assertIn("no-store", session["Cache-Control"])
        self.assertEqual(anonymous.get("/api/cypher/files/").json(), {"error": "authentication_required"})
        response = anonymous.post("/api/cypher/vault/", {}, content_type="application/json", HTTP_X_CSRFTOKEN=session.json()["csrf_token"])
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "authentication_required")

    def test_state_changes_require_csrf_and_work_without_telegram(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        payload = {"id": self.vault_id, "version": 1, "wrapped_key": encrypted(48)}
        self.assertIsNone(self.user.telegram_user_id)
        self.assertEqual(client.post("/api/cypher/vault/", payload, content_type="application/json").status_code, 403)
        token = client.get("/api/cypher/session/").json()["csrf_token"]
        self.assertEqual(client.post("/api/cypher/vault/", payload, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 201)
        self.assertEqual(client.post("/api/cypher/reset/", {}, content_type="application/json").status_code, 403)
        self.assertEqual(client.delete(f"/api/cypher/files/{uuid.uuid4()}/").status_code, 403)

    def test_create_and_session_return_encrypted_key_without_exposing_account_data(self):
        response = self.create_vault()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["vault"], {"id": self.vault_id, "version": 1, "wrapped_key": encrypted(48)})
        session = self.client.get("/api/cypher/session/").json()
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"], {"username": "owner", "email": "owner@example.test"})
        self.assertEqual(session["quota_bytes"], 50 * 1024 * 1024)
        self.assertEqual(session["vault"], response.json()["vault"])
        self.assertEqual(self.create_vault(vault_id=str(uuid.uuid4())).status_code, 409)
        self.assertEqual(self.create_vault(client=self.other_client).status_code, 409)

    def test_invalid_wrapping_envelopes_and_versions_are_rejected(self):
        bad_keys = [encrypted(47), {**encrypted(48), "iv": b64(b"a" * 11)}, {**encrypted(48), "name": "private.txt"}, {**encrypted(48), "ct": encrypted(48)["ct"] + "="}, {**encrypted(48), "v": True}]
        for wrapped_key in bad_keys:
            with self.subTest(wrapped_key=wrapped_key):
                response = self.client.post("/api/cypher/vault/", {"id": self.vault_id, "version": 1, "wrapped_key": wrapped_key}, content_type="application/json")
                self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/cypher/vault/", {"id": self.vault_id, "version": True, "wrapped_key": encrypted(48)}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Vault.objects.exists())

    def test_ciphertext_is_opaque_private_and_downloaded_without_scanning(self):
        self.create_vault()
        data = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" + b"tampered opaque ciphertext"
        with patch("drive.security.scan_path", side_effect=AssertionError("Do not scan encrypted data")):
            response = self.upload(data=data)
        self.assertEqual(response.status_code, 201)
        descriptor = response.json()["file"]
        self.assertEqual(set(descriptor), {"id", "vault_id", "metadata", "ciphertext_bytes", "created_at"})
        item = CipherFile.objects.get()
        self.assertEqual(item.ciphertext_bytes, len(data))
        self.assertNotIn("never-use", item.storage_key)
        self.assertTrue(item.storage_key.endswith(".bin"))
        self.assertFalse(BlobDeletion.objects.exists())
        listing = self.client.get("/api/cypher/files/").json()
        self.assertEqual(listing["files"], [descriptor])
        download = self.client.get(f"/api/cypher/files/{item.pk}/download/")
        self.assertEqual(b"".join(download.streaming_content), data)
        download.close()
        self.assertIn("no-store", download["Cache-Control"])
        self.assertEqual(download["Content-Type"], "application/octet-stream")
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.other_client.get("/api/cypher/files/").json(), {"files": []})
        self.assertEqual(self.other_client.get(f"/api/cypher/files/{item.pk}/download/").status_code, 404)
        self.assertEqual(self.other_client.delete(f"/api/cypher/files/{item.pk}/").status_code, 404)
        self.assertEqual(self.upload(client=self.other_client).status_code, 409)
        self.assertEqual(self.reset_vault(client=self.other_client).status_code, 409)

    def test_nested_envelope_values_are_rejected_without_debug_error(self):
        nested = "[" * 1500 + "0" + "]" * 1500
        body = '{"id":' + json.dumps(self.vault_id) + ',"version":1,"wrapped_key":{"v":1,"iv":' + nested + ',"ct":' + json.dumps(encrypted(48)["ct"]) + '}}'
        response = self.client.post("/api/cypher/vault/", body, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Vault.objects.exists())

    def test_bounds_metadata_and_duplicate_uploads(self):
        self.create_vault()
        self.assertEqual(self.upload(data=b"a" * 15).status_code, 413)
        with patch("vaults.views.MAX_CIPHERTEXT_BYTES", 32):
            self.assertEqual(self.upload(data=b"a" * 33).status_code, 413)
            self.assertEqual(self.upload(data=b"a" * 32).status_code, 201)
        for metadata in [{**encrypted(), "filename": "secret"}, {**encrypted(), "iv": "!"}, {**encrypted(), "ct": b64(b"x" * 15)}, {**encrypted(), "v": 2}, encrypted(8192), []]:
            with self.subTest(metadata_type=type(metadata).__name__):
                self.assertEqual(self.upload(metadata=metadata).status_code, 400)
        file_id = str(uuid.uuid4())
        self.assertEqual(self.upload(file_id=file_id, data=b"a" * 16).status_code, 201)
        self.assertEqual(self.upload(file_id=file_id, data=b"b" * 16).status_code, 409)
        self.assertEqual(CipherFile.objects.count(), 2)
        self.assertEqual(len(list(Path(self.media.name).rglob("*.bin"))), 2)

    def test_quota_includes_legacy_and_reserved_bytes_exactly(self):
        self.user.used_bytes = 10
        self.user.reserved_bytes = 3
        self.user.quota_bytes = 29
        self.user.save(update_fields=["used_bytes", "reserved_bytes", "quota_bytes"])
        self.create_vault()
        first = self.upload(data=b"a" * 16)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.upload(data=b"b" * 16).status_code, 409)
        session = self.client.get("/api/cypher/session/").json()
        self.assertEqual(session["used_bytes"], 26)
        self.assertEqual(session["reserved_bytes"], 3)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.delete(f"/api/cypher/files/{first.json()['file']['id']}/").status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 10)
        self.assertEqual(self.user.reserved_bytes, 3)
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))

    def test_failed_database_publication_rolls_back_quota_and_cleans_storage(self):
        self.create_vault()
        with patch("vaults.views.CipherFile.objects.create", side_effect=RuntimeError("simulated DB failure")):
            self.assertEqual(self.upload().status_code, 500)
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 0)
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(BlobDeletion.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))

    def test_storage_failure_after_partial_write_is_cleaned(self):
        self.create_vault()
        real_save = default_storage.save

        def fail_after_write(name, content):
            real_save(name, content)
            raise OSError("disk error")

        with patch("vaults.views.default_storage.save", side_effect=fail_after_write):
            self.assertEqual(self.upload().status_code, 500)
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))
        self.assertFalse(BlobDeletion.objects.exists())

    def test_reset_revokes_old_vault_keeps_legacy_and_uses_a_new_identity(self):
        legacy_key = default_storage.save("legacy/keep.bin", SimpleUploadedFile("keep.bin", b"legacy"))
        legacy = StoredFile.objects.create(owner=self.user, display_name="keep", blob=legacy_key, size=6)
        self.user.used_bytes = 6
        self.user.save(update_fields=["used_bytes"])
        self.create_vault()
        item_id = self.upload().json()["file"]["id"]
        self.assertEqual(self.reset_vault().status_code, 200)
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(BlobDeletion.objects.exists())
        vault = Vault.objects.get(pk=self.vault_id)
        self.assertIsNotNone(vault.revoked_at)
        self.assertEqual(vault.wrapped_key, {})
        self.assertEqual(self.client.get(f"/api/cypher/files/{item_id}/download/").status_code, 404)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.create_vault().status_code, 409)
        self.assertEqual(self.create_vault(vault_id=str(uuid.uuid4())).status_code, 201)
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 6)
        self.assertTrue(StoredFile.objects.filter(pk=legacy.pk).exists())
        self.assertTrue(default_storage.exists(legacy_key))

    def test_reset_during_upload_prevents_stale_publication(self):
        self.create_vault()
        real_save = default_storage.save

        def reset_after_write(name, content):
            result = real_save(name, content)
            self.assertEqual(self.reset_vault().status_code, 200)
            return result

        with patch("vaults.views.default_storage.save", side_effect=reset_after_write):
            self.assertEqual(self.upload().status_code, 409)
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 0)
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(BlobDeletion.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))

    def test_quota_is_checked_again_after_storage_write(self):
        self.create_vault()
        real_save = default_storage.save

        def consume_quota(name, content):
            result = real_save(name, content)
            get_user_model().objects.filter(pk=self.user.pk).update(used_bytes=self.user.quota_bytes)
            return result

        with patch("vaults.views.default_storage.save", side_effect=consume_quota):
            self.assertEqual(self.upload().json()["error"], "quota_exceeded")
        self.assertFalse(CipherFile.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))

    def test_failed_purge_has_durable_retry_and_account_cascade_cleanup(self):
        self.create_vault()
        self.upload()
        with patch("vaults.services.default_storage.delete", side_effect=OSError("storage offline")):
            self.assertEqual(self.reset_vault().status_code, 200)
        self.assertFalse(CipherFile.objects.exists())
        self.assertTrue(BlobDeletion.objects.exists())
        job = BlobDeletion.objects.get()
        self.assertGreaterEqual(job.attempts, 1)
        self.assertEqual(job.last_error, "OSError")
        BlobDeletion.objects.update(not_before=timezone.now() - timedelta(seconds=1))
        call_command("cleanup_cipher_blobs", stdout=io.StringIO())
        self.assertFalse(BlobDeletion.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))
        self.vault_id = str(uuid.uuid4())
        self.create_vault()
        self.upload()
        with self.captureOnCommitCallbacks(execute=True):
            self.user.delete()
        self.assertFalse(list(Path(self.media.name).rglob("*.bin")))
        self.assertFalse(CipherFile.objects.exists())

    def test_cleanup_collects_abandoned_staging_but_never_published_blobs(self):
        self.create_vault()
        self.upload()
        item = CipherFile.objects.get()
        BlobDeletion.objects.create(storage_key=item.storage_key)
        orphan_key = default_storage.save("cypher/orphan.bin", SimpleUploadedFile("unused", b"partial"))
        BlobDeletion.objects.create(storage_key=orphan_key)
        call_command("cleanup_cipher_blobs", stdout=io.StringIO())
        self.assertTrue(default_storage.exists(item.storage_key))
        self.assertFalse(default_storage.exists(orphan_key))
        self.assertFalse(BlobDeletion.objects.exists())

    def test_reset_needs_exact_confirmation(self):
        self.create_vault()
        response = self.client.post("/api/cypher/reset/", {"vault_id": self.vault_id, "confirmation": "delete"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Vault.objects.filter(revoked_at__isnull=True).exists())
