from accounts.test_support import completed_account
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from drive.models import Folder, StoredFile

from .models import FileGrant, ShareLink
from .services import SESSION_GRANTS_KEY

User = get_user_model()
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="cloud-nimbus-sharing-tests-")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SharingFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="Long-passphrase-778!",
            email_verified=True,
        )
        self.member = User.objects.create_user(
            username="member",
            email="member@example.com",
            password="Long-passphrase-778!",
            email_verified=True,
        )
        self.file = StoredFile.objects.create(
            owner=self.owner,
            display_name="notes.txt",
            blob=SimpleUploadedFile("notes.txt", b"hello nimbus", content_type="text/plain"),
            size=12,
            content_type="text/plain",
            scan_status=StoredFile.ScanStatus.CLEAN,
        )

    def create_link(self, mode=ShareLink.AccessMode.ANYONE, password=None, **kwargs):
        link = ShareLink(owner=self.owner, file=self.file, access_mode=mode, **kwargs)
        if password:
            link.set_password(password)
        link.full_clean()
        link.save()
        return link

    def assert_download(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(b"".join(response.streaming_content), b"hello nimbus")

    def test_anyone_link_downloads_for_anonymous_user(self):
        link = self.create_link()
        self.assert_download(self.client.get(reverse("sharing:public_share", args=[link.public_token])))

    def test_owner_manage_page_renders_existing_link(self):
        link = self.create_link(expires_at=timezone.now() + timedelta(days=1))
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        response = self.client.get(reverse("sharing:file_shares", args=[self.file.pk]))
        self.assertContains(response, self.file.display_name)
        self.assertContains(response, reverse("sharing:public_share", args=[link.public_token]))

    def test_signed_in_link_redirects_anonymous_and_downloads_for_member(self):
        link = self.create_link(ShareLink.AccessMode.SIGNED_IN)
        url = reverse("sharing:public_share", args=[link.public_token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

        self.client.force_login(self.member)
        completed_account(self.client, self.member)
        self.assert_download(self.client.get(url))

    def test_password_link_requires_login_then_records_token_revision(self):
        link = self.create_link(ShareLink.AccessMode.PASSWORD, password="share-pass-42")
        url = reverse("sharing:public_share", args=[link.public_token])
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.member)
        completed_account(self.client, self.member)
        self.assertContains(self.client.get(url), "Пароль ссылки")
        self.assertContains(self.client.post(url, {"password": "wrong-pass"}), "Неверный пароль")
        response = self.client.post(url, {"password": "share-pass-42"})
        self.assertRedirects(response, url)
        session_grant = self.client.session[SESSION_GRANTS_KEY][str(link.pk)]
        self.assertEqual(session_grant["revision"], link.revision)
        self.assertEqual(session_grant["user_id"], self.member.pk)
        self.assert_download(self.client.get(url))

    def test_password_change_only_invalidates_existing_session_when_requested(self):
        link = self.create_link(ShareLink.AccessMode.PASSWORD, password="share-pass-42")
        url = reverse("sharing:public_share", args=[link.public_token])
        member = Client()
        member.force_login(self.member)
        completed_account(member, self.member)
        member.post(url, {"password": "share-pass-42"})

        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        update_url = reverse("sharing:update", args=[link.pk])
        self.client.post(update_url, {"access_mode": "password", "password": "new-share-pass", "expires_at": ""})
        link.refresh_from_db()
        self.assertEqual(link.revision, 1)
        self.assertTrue(link.check_password("new-share-pass"))
        self.assert_download(member.get(url))

        self.client.post(
            update_url,
            {"access_mode": "password", "password": "newer-share-pass", "expires_at": "", "invalidate_existing": "on"},
        )
        link.refresh_from_db()
        self.assertEqual(link.revision, 2)
        self.assertContains(member.get(url), "Пароль ссылки")

    def test_owner_routes_enforce_ownership_and_revoke_always_increments_revision(self):
        link = self.create_link()
        self.client.force_login(self.member)
        completed_account(self.client, self.member)
        self.assertEqual(self.client.post(reverse("sharing:revoke", args=[link.pk])).status_code, 404)

        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        self.client.post(reverse("sharing:revoke", args=[link.pk]))
        link.refresh_from_db()
        self.assertFalse(link.active)
        self.assertEqual(link.revision, 2)
        self.assertEqual(self.client.get(reverse("sharing:public_share", args=[link.public_token])).status_code, 404)

    def test_create_and_revoke_all_owner_links(self):
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        response = self.client.post(
            reverse("sharing:create", args=[self.file.pk]),
            {"access_mode": "password", "password": "created-pass", "expires_at": ""},
        )
        self.assertRedirects(response, reverse("sharing:file_shares", args=[self.file.pk]))
        created = ShareLink.objects.get(file=self.file)
        self.assertNotEqual(created.password_hash, "created-pass")
        second = self.create_link()

        self.client.post(reverse("sharing:revoke_all", args=[self.file.pk]))
        created.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(created.active)
        self.assertFalse(second.active)
        self.assertEqual(created.revision, 2)
        self.assertEqual(second.revision, 2)

    def test_expired_link_is_unavailable(self):
        link = self.create_link(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(reverse("sharing:public_share", args=[link.public_token])).status_code, 404)

    def test_quarantined_file_and_deleting_owner_are_unavailable(self):
        link = self.create_link()
        url = reverse("sharing:public_share", args=[link.public_token])
        self.file.scan_status = StoredFile.ScanStatus.INFECTED
        self.file.save(update_fields=["scan_status"])
        self.assertEqual(self.client.get(url).status_code, 404)

        self.file.scan_status = StoredFile.ScanStatus.CLEAN
        self.file.save(update_fields=["scan_status"])
        self.owner.scheduled_deletion_at = timezone.now() + timedelta(days=30)
        self.owner.save(update_fields=["scheduled_deletion_at"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_file_grant_accepts_user_or_email_and_normalizes_email(self):
        by_user = FileGrant(file=self.file, granted_by=self.owner, user=self.member, role=FileGrant.Role.EDITOR)
        by_user.full_clean()
        by_user.save()
        self.assertEqual(by_user.email, self.member.email)

        by_email = FileGrant(file=self.file, granted_by=self.owner, email="Invitee@Example.COM")
        by_email.full_clean()
        by_email.save()
        self.assertEqual(by_email.email, "invitee@example.com")

    def test_restricted_link_requires_matching_grant(self):
        link = self.create_link(ShareLink.AccessMode.RESTRICTED)
        url = reverse("sharing:public_share", args=[link.public_token])
        self.client.force_login(self.member)
        completed_account(self.client, self.member)
        self.assertEqual(self.client.get(url).status_code, 404)
        FileGrant.objects.create(file=self.file, granted_by=self.owner, user=self.member, email=self.member.email)
        self.assert_download(self.client.get(url))

    def test_share_capability_is_signed_and_not_stored_raw(self):
        link = self.create_link()
        token = link.public_token
        self.assertNotIn(token, str(ShareLink.objects.filter(pk=link.pk).values().first()))
        damaged = token[:-1] + ("A" if token[-1] != "A" else "B")
        self.assertEqual(self.client.get(reverse("sharing:public_share", args=[damaged])).status_code, 404)

    def test_share_dialog_api_is_owner_only_and_has_simple_general_state(self):
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        url = reverse("sharing:item_state", args=["file", self.file.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["general"]["mode"], ShareLink.AccessMode.RESTRICTED)
        self.client.force_login(self.member)
        completed_account(self.client, self.member)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_shared_folder_browses_descendants_and_blocks_outside_file(self):
        root = Folder.objects.create(owner=self.owner, name="Campaign")
        child = Folder.objects.create(owner=self.owner, parent=root, name="Assets")
        inside = StoredFile.objects.create(
            owner=self.owner,
            folder=child,
            display_name="brief.txt",
            blob=SimpleUploadedFile("brief.txt", b"inside", content_type="text/plain"),
            size=6,
            content_type="text/plain",
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        outside = StoredFile.objects.create(
            owner=self.owner,
            display_name="private.txt",
            blob=SimpleUploadedFile("private.txt", b"outside", content_type="text/plain"),
            size=7,
            content_type="text/plain",
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        link = ShareLink.objects.create(owner=self.owner, folder=root, access_mode=ShareLink.AccessMode.ANYONE)
        token = link.public_token
        root_url = reverse("sharing:public_share", args=[token])
        response = self.client.get(root_url)
        self.assertContains(response, "Assets")
        self.assertEqual(response.headers["Referrer-Policy"], "origin")
        child_url = reverse("sharing:public_share_folder", args=[token, child.pk])
        self.assertContains(self.client.get(child_url), "brief.txt")
        inside_response = self.client.get(reverse("sharing:public_share_file", args=[token, inside.pk]))
        self.assertEqual(b"".join(inside_response.streaming_content), b"inside")
        self.assertEqual(self.client.get(reverse("sharing:public_share_file", args=[token, outside.pk])).status_code, 404)

    def test_folder_invite_creates_restricted_link_and_allows_member(self):
        folder = Folder.objects.create(owner=self.owner, name="Photos")
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        response = self.client.post(
            reverse("sharing:item_grant", args=["folder", folder.pk]),
            {"email": self.member.email, "role": FileGrant.Role.VIEWER},
        )
        self.assertEqual(response.status_code, 200)
        link = ShareLink.objects.get(folder=folder, active=True)
        self.assertEqual(link.access_mode, ShareLink.AccessMode.RESTRICTED)
        self.assertTrue(FileGrant.objects.filter(folder=folder, user=self.member).exists())
        self.client.force_login(self.member)
        completed_account(self.client, self.member)
        self.assertEqual(self.client.get(reverse("sharing:public_share", args=[link.public_token])).status_code, 200)

    def test_registered_member_can_disable_share_emails(self):
        self.member.email_share_notifications = False
        self.member.save(update_fields=["email_share_notifications"])
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        response = self.client.post(
            reverse("sharing:item_grant", args=["file", self.file.pk]),
            {"email": self.member.email, "role": FileGrant.Role.VIEWER},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_external_invitee_always_receives_the_access_link(self):
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        response = self.client.post(
            reverse("sharing:item_grant", args=["file", self.file.pk]),
            {"email": "outside@example.com", "role": FileGrant.Role.VIEWER},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_invited_member_finds_folder_in_shared_with_me_and_revoke_removes_it(self):
        folder = Folder.objects.create(owner=self.owner, name="Research")
        link = ShareLink.objects.create(owner=self.owner, folder=folder, access_mode=ShareLink.AccessMode.RESTRICTED)
        grant = FileGrant.objects.create(
            folder=folder,
            granted_by=self.owner,
            user=self.member,
            email=self.member.email,
            role=FileGrant.Role.VIEWER,
        )
        member_client = Client()
        member_client.force_login(self.member)
        completed_account(member_client, self.member)
        page = member_client.get(reverse("sharing:shared_with_me"))
        self.assertContains(page, "Research")
        self.assertContains(page, self.owner.email)
        self.assertContains(page, reverse("sharing:public_share", args=[link.public_token]))

        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        self.client.post(reverse("sharing:revoke_grant", args=[grant.pk]))
        page = member_client.get(reverse("sharing:shared_with_me"))
        self.assertNotContains(page, "Research")
        self.assertEqual(member_client.get(reverse("sharing:public_share", args=[link.public_token])).status_code, 404)

    def test_share_dialog_rejects_inviting_the_owner(self):
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        response = self.client.post(
            reverse("sharing:item_grant", args=["file", self.file.pk]),
            {"email": self.owner.email, "role": FileGrant.Role.VIEWER},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "cannot_share_with_self")
        self.assertFalse(FileGrant.objects.filter(file=self.file).exists())

    def test_revoked_link_cannot_be_reactivated_through_update(self):
        link = self.create_link()
        self.client.force_login(self.owner)
        completed_account(self.client, self.owner)
        self.client.post(reverse("sharing:revoke", args=[link.pk]))
        response = self.client.post(
            reverse("sharing:update", args=[link.pk]),
            {"access_mode": "anyone", "expires_at": ""},
        )
        self.assertEqual(response.status_code, 404)
        link.refresh_from_db()
        self.assertFalse(link.active)
