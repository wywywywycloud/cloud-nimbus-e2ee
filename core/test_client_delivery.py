from accounts.test_support import completed_account, onboarding_session
from pathlib import Path
import tempfile
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from accounts.telegram import handle_update, api_call, TelegramAPIError
from core.client import CLIENT_CSP


@override_settings(TELEGRAM_ENABLED=False, NIMBUS_LEGACY_WRITES_ENABLED=False)
class DeliveryAndDisabledIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delivery-test", email="delivery@example.invalid", password="Test-only-829!", email_verified=True)

    def test_static_client_exact_bytes_and_public_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            content = b'<!doctype html><title>Exact bytes</title>\n'
            Path(directory, "index.html").write_bytes(content)
            Path(directory, "verify.html").write_bytes(b"How to verify")
            with self.settings(CYPHER_CLIENT_ROOT=directory):
                response = self.client.get("/vault/")
                self.assertEqual(response.content, content)
                self.assertEqual(response["Content-Security-Policy"], CLIENT_CSP)
                self.assertEqual(response["Cache-Control"], "no-store")
                self.assertEqual(self.client.get("/vault/verify.html").status_code, 200)
                self.assertEqual(self.client.get("/vault/../settings.py").status_code, 404)
                self.assertEqual(self.client.get("/vault/.env").status_code, 404)
        with self.settings(OPAQUE_ENABLED=False):
            login = self.client.get("/auth/login/")
            self.assertRedirects(login, '/vault/', fetch_redirect_response=False)

    def test_telegram_disabled_without_network_or_state_change(self):
        with patch("accounts.telegram.urlopen") as network:
            self.assertFalse(handle_update({"message": {"text": "/start anything"}}))
            with self.assertRaises(TelegramAPIError):
                api_call("getMe")
            network.assert_not_called()
        with self.assertRaises(CommandError):
            call_command("run_telegram_bot")
        self.assertEqual(self.client.post("/auth/telegram/webhook/", data="{}", content_type="application/json").status_code, 410)
        self.client.force_login(self.user)
        onboarding_session(self.client, self.user)
        self.assertEqual(self.client.post("/auth/telegram/link/").status_code, 503)
        self.assertEqual(self.client.get("/auth/telegram/status/").json(), {"enabled": False, "linked": False})
        self.assertEqual(self.client.get("/auth/settings/").status_code, 403)

    def test_plaintext_ingress_is_closed_including_old_upload_sessions(self):
        self.client.force_login(self.user)
        completed_account(self.client, self.user)
        self.assertRedirects(self.client.get("/"), "/vault/", fetch_redirect_response=False)
        uid = uuid.uuid4()
        for method, path in [("post", "/upload/"), ("post", "/api/uploads/initiate/"),
                             ("put", f"/api/uploads/{uid}/parts/0/"), ("post", f"/api/uploads/{uid}/complete/")]:
            with self.subTest(path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 410)
