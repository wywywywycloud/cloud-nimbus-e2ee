import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import OneTimeCode, TelegramLinkAttempt
from .telegram import handle_update

User = get_user_model()


def code_from_last_email():
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


@override_settings(OPAQUE_ENABLED=False)
class RegistrationTests(TestCase):
    def test_registration_requires_email_code(self):
        response = self.client.post(reverse("accounts:register"), {
            "username": "mikhail",
            "email": "mikhail@example.com",
            "password1": "Cloudy-Pebble-827!",
            "password2": "Cloudy-Pebble-827!",
        })
        self.assertRedirects(response, reverse("accounts:verify_email"))
        user = User.objects.get(username="mikhail")
        self.assertFalse(user.email_verified)
        self.assertEqual(user.auth_mode, User.AuthMode.CODE)
        self.assertEqual(user.quota_bytes, settings.TELEGRAM_VERIFIED_QUOTA_BYTES)
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(reverse("accounts:verify_email"), {"code": code_from_last_email()})
        self.assertRedirects(response, reverse("accounts:settings"))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_code_is_single_use(self):
        user = User.objects.create_user(username="cloud", email="cloud@example.com", password="Long-passphrase-778!", email_verified=True)
        otp = OneTimeCode.issue(user, OneTimeCode.Purpose.LOGIN, "123456")
        self.assertTrue(otp.verify("123456"))
        self.assertFalse(otp.verify("123456"))


@override_settings(NIMBUS_LEGACY_WRITES_ENABLED=True, OPAQUE_ENABLED=False)
class LoginModeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="nimbus", email="nimbus@example.com", password="Long-passphrase-778!", email_verified=True)

    def test_default_code_login(self):
        response = self.client.post(reverse("accounts:login"), {"identifier": self.user.email})
        self.assertRedirects(response, reverse("accounts:verify_login"))
        response = self.client.post(reverse("accounts:verify_login"), {"code": code_from_last_email()})
        self.assertRedirects(response, reverse("drive:home"))

    def test_password_only_login(self):
        self.user.auth_mode = User.AuthMode.PASSWORD
        self.user.save(update_fields=["auth_mode"])
        response = self.client.post(reverse("accounts:login"), {"identifier": "nimbus", "password": "Long-passphrase-778!"})
        self.assertRedirects(response, reverse("drive:home"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_mode_discovery_is_a_clean_first_step(self):
        self.user.auth_mode = User.AuthMode.PASSWORD
        self.user.save(update_fields=["auth_mode"])
        response = self.client.post(reverse("accounts:login"), {"identifier": "nimbus"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="password_step" value="1"', html=False)
        self.assertContains(response, 'value="nimbus"', html=False)
        self.assertNotContains(response, "Обязательное поле")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_and_password_login(self):
        self.user.auth_mode = User.AuthMode.CODE_PASSWORD
        self.user.save(update_fields=["auth_mode"])
        response = self.client.post(reverse("accounts:login"), {"identifier": "nimbus", "password": "Long-passphrase-778!"})
        self.assertRedirects(response, reverse("accounts:verify_login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("accounts:verify_login"), {"code": code_from_last_email()})
        self.assertRedirects(response, reverse("drive:home"))

    def test_admin_uses_the_users_configured_login_flow(self):
        self.user.is_staff = True
        self.user.auth_mode = User.AuthMode.CODE
        self.user.save(update_fields=["is_staff", "auth_mode"])
        response = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(response, f"{reverse('accounts:login')}?next=/admin/", fetch_redirect_response=False)
        self.client.get(response.url)
        self.client.post(reverse("accounts:login"), {"identifier": self.user.email})
        response = self.client.post(reverse("accounts:verify_login"), {"code": code_from_last_email()})
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)

    def test_username_reminder_response_is_neutral(self):
        response = self.client.post(reverse("accounts:remind_username"), {"email": "missing@example.com"}, follow=True)
        self.assertContains(response, "Если аккаунт существует")
        self.assertEqual(len(mail.outbox), 0)

    def test_account_deletion_can_be_recovered_within_grace_period(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:delete_account"), {"username": "nimbus", "password": "Long-passphrase-778!"})
        self.assertRedirects(response, reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.scheduled_deletion_at)
        recovery_url = re.search(r"https?://[^\s]+", mail.outbox[-1].body).group(0)
        recovery_path = recovery_url.split("testserver", 1)[-1]
        page = self.client.get(recovery_path)
        self.assertContains(page, "Восстановить аккаунт")
        self.client.post(recovery_path)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertIsNone(self.user.scheduled_deletion_at)

    def test_password_reset_only_emails_verified_active_user(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": self.user.email})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)


@override_settings(NIMBUS_LEGACY_WRITES_ENABLED=True, OPAQUE_ENABLED=False)
class UserPreferencesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="preferences",
            email="preferences@example.com",
            password="Long-passphrase-778!",
            email_verified=True,
        )
        self.client.force_login(self.user)

    def test_defaults_are_dark_and_russian(self):
        self.assertEqual(self.user.ui_theme, User.UITheme.DARK)
        self.assertEqual(self.user.language, "ru")

    def test_preferences_are_saved_without_security_password(self):
        url = reverse("accounts:interface_settings")
        response = self.client.post(url, {
            "action": "preferences",
            "ui_theme": User.UITheme.LIGHT,
            "language": "ar",
            "default_view_mode": User.ViewMode.LIST,
            "display_density": User.DisplayDensity.COMPACT,
            "default_file_sort": User.FileSort.SIZE,
            "folders_first": "on",
        })
        self.assertRedirects(response, url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.ui_theme, User.UITheme.LIGHT)
        self.assertEqual(self.user.language, "ar")
        self.assertEqual(self.user.default_view_mode, User.ViewMode.LIST)
        self.assertEqual(self.user.display_density, User.DisplayDensity.COMPACT)
        self.assertEqual(self.user.default_file_sort, User.FileSort.SIZE)
        self.assertFalse(self.user.show_image_previews)
        self.assertEqual(self.user.auth_mode, User.AuthMode.CODE)
        self.assertEqual(self.client.session["django_language"], "ar")
        self.assertEqual(self.client.session["ui_theme"], "light")

    def test_security_form_still_requires_correct_current_password(self):
        url = reverse("accounts:settings")
        response = self.client.post(url, {
            "action": "auth_mode",
            "auth_mode": User.AuthMode.PASSWORD,
            "current_password": "wrong-password",
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_mode, User.AuthMode.CODE)
        self.assertContains(response, "Неверный пароль")

        response = self.client.post(url, {
            "action": "auth_mode",
            "auth_mode": User.AuthMode.PASSWORD,
            "current_password": "Long-passphrase-778!",
        })
        self.assertRedirects(response, url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_mode, User.AuthMode.PASSWORD)

    def test_authenticated_preferences_set_html_language_direction_and_theme(self):
        self.user.language = "ur"
        self.user.ui_theme = User.UITheme.LIGHT
        self.user.save(update_fields=["language", "ui_theme"])
        response = self.client.get(reverse("accounts:settings"))
        self.assertContains(response, '<html lang="ur" dir="rtl" data-theme="light"', html=False)
        self.assertEqual(response.headers["Content-Language"], "ur")

    def test_anonymous_session_preferences_are_applied(self):
        self.client.logout()
        session = self.client.session
        session["django_language"] = "ar"
        session["ui_theme"] = "light"
        session.save()
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, '<html lang="ar" dir="rtl" data-theme="light"', html=False)

    def test_settings_are_split_into_independent_sections(self):
        account = self.client.get(reverse("accounts:settings"))
        storage = self.client.get(reverse("accounts:storage_settings"))
        interface = self.client.get(reverse("accounts:interface_settings"))
        self.assertContains(account, "Аккаунт и безопасность")
        self.assertContains(account, "Способ входа")
        self.assertNotContains(account, "Крупные файлы")
        self.assertContains(storage, "Использование места")
        self.assertContains(storage, "Крупные файлы")
        self.assertNotContains(storage, "Способ входа")
        self.assertContains(interface, "Внешний вид и поведение")
        self.assertContains(interface, "Показывать превью изображений")

    def test_notification_preference_is_saved_on_account_section(self):
        response = self.client.post(reverse("accounts:settings"), {"action": "notifications"})
        self.assertRedirects(response, reverse("accounts:settings"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_share_notifications)

    def test_interface_post_is_rejected_from_account_section(self):
        response = self.client.post(reverse("accounts:settings"), {"action": "preferences"})
        self.assertEqual(response.status_code, 400)

    def test_language_catalog_has_required_set_without_ukrainian(self):
        codes = {code for code, _label in settings.LANGUAGES}
        eu_codes = {
            "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
            "ga", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv",
        }
        self.assertEqual(codes, {"ru", "ar", "ur", "hi"} | eu_codes)
        self.assertNotIn("uk", codes)


@override_settings(TELEGRAM_ENABLED=True)
class TelegramLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="telegram-user",
            email="telegram@example.com",
            password="Long-passphrase-778!",
            email_verified=True,
            quota_bytes=settings.TELEGRAM_VERIFIED_QUOTA_BYTES,
        )
        self.client.force_login(self.user)

    def issue_attempt(self, token="safe_token-123"):
        return TelegramLinkAttempt.objects.create(
            user=self.user,
            token_digest=TelegramLinkAttempt.digest_token(token),
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    @override_settings(TELEGRAM_BOT_TOKEN="bot-token", TELEGRAM_BOT_USERNAME="nimbus_test_bot")
    def test_link_view_creates_one_time_deep_link(self):
        response = self.client.post(reverse("accounts:telegram_link"))
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response.url)
        token = parse_qs(parsed.query)["start"][0]
        self.assertEqual(parsed.netloc, "t.me")
        self.assertEqual(parsed.path, "/nimbus_test_bot")
        self.assertTrue(TelegramLinkAttempt.objects.filter(user=self.user, token_digest=TelegramLinkAttempt.digest_token(token)).exists())

    @patch("accounts.telegram.send_message")
    def test_bot_requests_only_the_current_users_contact(self, send_message):
        attempt = self.issue_attempt()
        update = {"message": {"chat": {"id": 501, "type": "private"}, "from": {"id": 7001, "first_name": "Mikhail"}, "text": "/start safe_token-123"}}
        self.assertTrue(handle_update(update))
        attempt.refresh_from_db()
        self.assertEqual(attempt.telegram_sender_id, 7001)
        markup = send_message.call_args.kwargs["reply_markup"]
        self.assertTrue(markup["keyboard"][0][0]["request_contact"])

    @patch("accounts.telegram.send_message")
    def test_foreign_contact_is_rejected(self, send_message):
        attempt = self.issue_attempt()
        attempt.telegram_chat_id = 501
        attempt.telegram_sender_id = 7001
        attempt.save(update_fields=["telegram_chat_id", "telegram_sender_id"])
        update = {"message": {"chat": {"id": 501, "type": "private"}, "from": {"id": 7001}, "contact": {"user_id": 9999, "phone_number": "+79990000000"}}}
        self.assertFalse(handle_update(update))
        self.user.refresh_from_db()
        self.assertIsNone(self.user.telegram_user_id)
        self.assertIn("только собственный", send_message.call_args.args[1])

    @patch("accounts.telegram.send_message")
    def test_own_contact_links_telegram_and_unlocks_quota(self, send_message):
        attempt = self.issue_attempt()
        attempt.telegram_chat_id = 501
        attempt.telegram_sender_id = 7001
        attempt.save(update_fields=["telegram_chat_id", "telegram_sender_id"])
        update = {"message": {"chat": {"id": 501, "type": "private"}, "from": {"id": 7001, "username": "mikhail", "first_name": "Mikhail"}, "contact": {"user_id": 7001, "phone_number": "+79990000000"}}}
        self.assertTrue(handle_update(update))
        self.user.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(self.user.telegram_user_id, 7001)
        self.assertEqual(self.user.telegram_username, "mikhail")
        self.assertEqual(self.user.quota_bytes, settings.TELEGRAM_VERIFIED_QUOTA_BYTES)
        self.assertIsNotNone(attempt.used_at)

    @patch("accounts.telegram.send_message")
    def test_existing_user_can_rebind_to_another_telegram(self, send_message):
        self.user.telegram_user_id = 7001
        self.user.quota_bytes = settings.TELEGRAM_VERIFIED_QUOTA_BYTES
        self.user.save(update_fields=["telegram_user_id", "quota_bytes"])
        attempt = self.issue_attempt("another-token")
        attempt.telegram_chat_id = 502
        attempt.telegram_sender_id = 7002
        attempt.save(update_fields=["telegram_chat_id", "telegram_sender_id"])
        update = {"message": {"chat": {"id": 502, "type": "private"}, "from": {"id": 7002, "first_name": "New"}, "contact": {"user_id": 7002, "phone_number": "+70000000000"}}}
        self.assertTrue(handle_update(update))
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_user_id, 7002)
        self.assertEqual(self.user.quota_bytes, settings.TELEGRAM_VERIFIED_QUOTA_BYTES)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="webhook-secret")
    @patch("accounts.views.handle_update")
    def test_webhook_requires_secret_header(self, handle):
        url = reverse("accounts:telegram_webhook")
        self.assertEqual(self.client.post(url, data="{}", content_type="application/json").status_code, 403)
        response = self.client.post(url, data="{}", content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="webhook-secret")
        self.assertEqual(response.status_code, 200)
        handle.assert_called_once_with({})
