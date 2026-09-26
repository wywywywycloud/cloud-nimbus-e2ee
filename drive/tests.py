from accounts.test_support import completed_account
import tempfile
import json
import hashlib
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import MAX_USER_BYTES
from .models import Folder, StoredFile, UploadSession

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="cloud-nimbus-tests-"), NIMBUS_LEGACY_WRITES_ENABLED=True, TELEGRAM_ENABLED=True)
class FileFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", email="owner@example.com", password="Long-passphrase-778!", email_verified=True, telegram_user_id=1001)
        self.other = User.objects.create_user(username="other", email="other@example.com", password="Long-passphrase-778!", email_verified=True, telegram_user_id=1002)
        self.client.force_login(self.user)
        completed_account(self.client, self.user)

    def test_upload_download_rename_favorite_delete(self):
        response = self.client.post(reverse("drive:upload"), {"files": SimpleUploadedFile("notes.txt", b"hello nimbus", content_type="text/plain")})
        self.assertRedirects(response, reverse("drive:home"))
        item = StoredFile.objects.get(owner=self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 12)

        response = self.client.get(reverse("drive:download", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])

        self.client.post(reverse("drive:rename", args=[item.pk]), {"name": "renamed.txt"})
        self.client.post(reverse("drive:favorite", args=[item.pk]))
        item.refresh_from_db()
        self.assertEqual(item.display_name, "renamed.txt")
        self.assertTrue(item.favorite)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("drive:delete", args=[item.pk]))
        self.assertFalse(StoredFile.objects.filter(pk=item.pk).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 0)

    def test_other_users_file_is_not_accessible(self):
        item = StoredFile.objects.create(owner=self.other, display_name="secret.txt", blob=SimpleUploadedFile("secret.txt", b"secret"), size=6, content_type="text/plain")
        self.assertEqual(self.client.get(reverse("drive:download", args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("drive:delete", args=[item.pk])).status_code, 404)

    def test_quota_is_enforced(self):
        self.user.used_bytes = MAX_USER_BYTES - 2
        self.user.save(update_fields=["used_bytes"])
        response = self.client.post(reverse("drive:upload"), {"files": SimpleUploadedFile("too-big.txt", b"123")}, follow=True)
        self.assertContains(response, "Недостаточно места")
        self.assertFalse(StoredFile.objects.filter(owner=self.user).exists())

    def test_new_account_must_link_telegram_before_uploading(self):
        self.user.quota_bytes = MAX_USER_BYTES
        self.user.telegram_user_id = None
        self.user.save(update_fields=["quota_bytes", "telegram_user_id"])
        page = self.client.get(reverse("drive:home"))
        self.assertEqual(page.status_code, 403)
        response = self.client.post(reverse("drive:upload"), {"files": SimpleUploadedFile("locked.txt", b"locked")}, follow=True)
        self.assertEqual(response.status_code, 403)
        api = self.client.post(
            reverse("drive:upload_initiate"),
            json.dumps({"name": "locked.bin", "size": 6, "content_type": "application/octet-stream"}),
            content_type="application/json",
        )
        self.assertEqual(api.status_code, 403)
        self.assertEqual(api.json()["next_step"], "telegram")
        self.assertFalse(StoredFile.objects.filter(owner=self.user).exists())

    def test_filename_is_reduced_to_basename(self):
        self.client.post(reverse("drive:upload"), {"files": SimpleUploadedFile("../../escape.txt", b"safe")})
        item = StoredFile.objects.get(owner=self.user)
        self.assertEqual(item.display_name, "escape.txt")
        self.assertNotIn("..", Path(item.blob.name).parts)

    def test_profile_view_density_sort_and_folder_order_are_applied(self):
        self.user.default_view_mode = User.ViewMode.LIST
        self.user.display_density = User.DisplayDensity.COMPACT
        self.user.default_file_sort = User.FileSort.NAME
        self.user.folders_first = False
        self.user.save(update_fields=["default_view_mode", "display_density", "default_file_sort", "folders_first"])
        Folder.objects.create(owner=self.user, name="Zebra folder")
        StoredFile.objects.create(
            owner=self.user,
            display_name="Alpha file.txt",
            blob=SimpleUploadedFile("alpha.txt", b"alpha"),
            size=5,
            content_type="text/plain",
        )
        response = self.client.get(reverse("drive:home"))
        body = response.content.decode()
        self.assertIn('data-density="compact"', body)
        self.assertIn('data-default-view="list"', body)
        self.assertLess(body.index("Alpha file.txt"), body.index("Zebra folder"))

    def test_image_preview_preference_suppresses_preview_request(self):
        item = StoredFile.objects.create(
            owner=self.user,
            display_name="photo.jpg",
            blob=SimpleUploadedFile("photo.jpg", b"jpeg", content_type="image/jpeg"),
            size=4,
            content_type="image/jpeg",
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        preview_url = reverse("drive:preview", args=[item.pk])
        self.user.show_image_previews = False
        self.user.save(update_fields=["show_image_previews"])
        self.assertNotContains(self.client.get(reverse("drive:home")), preview_url)
        self.user.show_image_previews = True
        self.user.save(update_fields=["show_image_previews"])
        self.assertContains(self.client.get(reverse("drive:home")), preview_url)

    @override_settings(UPLOAD_CHUNK_BYTES=1024 * 1024, MAX_SINGLE_UPLOAD_BYTES=2 * 1024 * 1024)
    def test_resumable_upload_reserves_quota_and_completes(self):
        payload = json.dumps({"name": "large.bin", "size": 1024 * 1024 + 1, "content_type": "application/octet-stream"})
        first = self.client.post(reverse("drive:upload_initiate"), payload, content_type="application/json", HTTP_IDEMPOTENCY_KEY="same-upload")
        self.assertEqual(first.status_code, 200)
        session = first.json()
        repeated = self.client.post(reverse("drive:upload_initiate"), payload, content_type="application/json", HTTP_IDEMPOTENCY_KEY="same-upload")
        self.assertEqual(repeated.json()["upload_id"], session["upload_id"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.reserved_bytes, 1024 * 1024 + 1)

        part0 = b"a" * (1024 * 1024)
        part1 = b"b"
        for number, body in enumerate((part0, part1)):
            response = self.client.put(
                reverse("drive:upload_part", args=[session["upload_id"], number]),
                body,
                content_type="application/octet-stream",
                HTTP_X_CHUNK_SHA256=hashlib.sha256(body).hexdigest(),
            )
            self.assertEqual(response.status_code, 200)
        status = self.client.get(reverse("drive:upload_status", args=[session["upload_id"]])).json()
        self.assertEqual(status["received_parts"], [0, 1])
        complete = self.client.post(reverse("drive:upload_complete", args=[session["upload_id"]]))
        self.assertEqual(complete.status_code, 200)
        item = StoredFile.objects.get(owner=self.user, display_name="large.bin")
        self.assertEqual(item.size, len(part0) + len(part1))
        self.assertTrue(item.object_key)
        self.user.refresh_from_db()
        self.assertEqual(self.user.reserved_bytes, 0)
        self.assertEqual(self.user.used_bytes, len(part0) + len(part1))

    def test_eicar_marker_is_quarantined(self):
        body = b"prefix-EICAR-STANDARD-ANTIVIRUS-TEST-FILE-suffix"
        self.client.post(reverse("drive:upload"), {"files": SimpleUploadedFile("eicar.txt", body)})
        item = StoredFile.objects.get(owner=self.user)
        self.assertEqual(item.scan_status, StoredFile.ScanStatus.INFECTED)
        response = self.client.get(reverse("drive:download", args=[item.pk]))
        self.assertRedirects(response, reverse("drive:home"))

    def test_file_row_uses_compact_scan_status_and_visible_download(self):
        clean = StoredFile.objects.create(
            owner=self.user,
            display_name="clean.txt",
            blob=SimpleUploadedFile("clean.txt", b"clean"),
            size=5,
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        StoredFile.objects.create(
            owner=self.user,
            display_name="unverified.txt",
            blob=SimpleUploadedFile("unverified.txt", b"unknown"),
            size=7,
            scan_status=StoredFile.ScanStatus.ERROR,
        )

        response = self.client.get(reverse("drive:home"))

        self.assertContains(response, 'aria-label="Проверено на вирусы"', html=False)
        self.assertContains(response, 'aria-label="Не проверено на вирусы"', html=False)
        self.assertContains(response, f'aria-label="Скачать {clean.display_name}"', html=False)
        self.assertNotContains(response, "Сканер недоступен")

    def test_private_blob_is_not_exposed_by_media_url_even_in_debug(self):
        item = StoredFile.objects.create(
            owner=self.user,
            display_name="private.txt",
            blob=SimpleUploadedFile("private.txt", b"private"),
            size=7,
        )
        self.client.logout()
        self.assertEqual(self.client.get(item.blob.url).status_code, 404)

    def test_private_raster_preview_is_inline_and_owner_scoped(self):
        image = StoredFile.objects.create(
            owner=self.user,
            display_name="preview.png",
            blob=SimpleUploadedFile("preview.png", b"\x89PNG\r\n\x1a\npreview"),
            size=15,
            content_type="image/png",
            scan_status=StoredFile.ScanStatus.CLEAN,
        )
        text = StoredFile.objects.create(
            owner=self.user,
            display_name="notes.txt",
            blob=SimpleUploadedFile("notes.txt", b"notes"),
            size=5,
            content_type="text/plain",
            scan_status=StoredFile.ScanStatus.CLEAN,
        )

        response = self.client.get(reverse("drive:preview", args=[image.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertIn("inline", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        response.close()
        self.assertEqual(self.client.get(reverse("drive:preview", args=[text.pk])).status_code, 404)

        self.client.force_login(self.other)
        completed_account(self.client, self.other)
        self.assertEqual(self.client.get(reverse("drive:preview", args=[image.pk])).status_code, 404)

    def test_folder_navigation_is_owner_scoped_and_has_breadcrumbs(self):
        root = Folder.objects.create(owner=self.user, name="Projects")
        current = Folder.objects.create(owner=self.user, parent=root, name="Nimbus")
        child = Folder.objects.create(owner=self.user, parent=current, name="Design")
        visible = StoredFile.objects.create(
            owner=self.user,
            folder=current,
            display_name="visible.txt",
            blob=SimpleUploadedFile("visible.txt", b"visible"),
            size=7,
        )
        StoredFile.objects.create(
            owner=self.user,
            display_name="root-only.txt",
            blob=SimpleUploadedFile("root-only.txt", b"root"),
            size=4,
        )
        foreign = Folder.objects.create(owner=self.other, name="Foreign")

        response = self.client.get(reverse("drive:folder", args=[current.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_folder"], current)
        self.assertEqual(list(response.context["folders"]), [child])
        self.assertEqual(list(response.context["files"]), [visible])
        self.assertEqual(response.context["breadcrumbs"], [root, current])
        self.assertEqual(response.context["parent_folder"], root)
        self.assertEqual(self.client.get(reverse("drive:folder", args=[foreign.pk])).status_code, 404)

    def test_folder_size_includes_files_in_nested_folders(self):
        root = Folder.objects.create(owner=self.user, name="Root")
        child = Folder.objects.create(owner=self.user, parent=root, name="Child")
        grandchild = Folder.objects.create(owner=self.user, parent=child, name="Grandchild")
        StoredFile.objects.create(
            owner=self.user,
            folder=child,
            display_name="direct.txt",
            blob=SimpleUploadedFile("direct.txt", b"12345"),
            size=5,
        )
        StoredFile.objects.create(
            owner=self.user,
            folder=grandchild,
            display_name="nested.txt",
            blob=SimpleUploadedFile("nested.txt", b"1234567"),
            size=7,
        )

        response = self.client.get(reverse("drive:home"))

        [visible_root] = response.context["folders"]
        self.assertEqual(visible_root.total_size_bytes, 12)

    def test_folder_mutations_reject_foreign_parent_and_foreign_folder(self):
        foreign = Folder.objects.create(owner=self.other, name="Foreign")
        self.assertEqual(
            self.client.post(reverse("drive:folder_create"), {"name": "Stolen", "parent": foreign.pk}).status_code,
            404,
        )
        self.assertEqual(self.client.post(reverse("drive:folder_rename", args=[foreign.pk]), {"name": "Renamed"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("drive:folder_delete", args=[foreign.pk])).status_code, 404)
        self.assertFalse(Folder.objects.filter(owner=self.user, name="Stolen").exists())

    def test_folder_create_and_rename_routes_preserve_parent(self):
        parent = Folder.objects.create(owner=self.user, name="Parent")
        response = self.client.post(reverse("drive:folder_create"), {"name": "Drafts", "parent": parent.pk})
        self.assertRedirects(response, reverse("drive:folder", args=[parent.pk]))
        created = Folder.objects.get(owner=self.user, parent=parent, name="Drafts")

        response = self.client.post(reverse("drive:folder_rename", args=[created.pk]), {"name": "Ready"})
        self.assertRedirects(response, reverse("drive:folder", args=[parent.pk]))
        created.refresh_from_db()
        self.assertEqual(created.name, "Ready")
        self.assertEqual(created.parent, parent)

        self.client.post(reverse("drive:folder_create"), {"name": "ready", "parent": parent.pk})
        self.assertEqual(Folder.objects.filter(owner=self.user, parent=parent).count(), 1)

    def test_folder_model_rejects_cycles_cross_owner_parent_and_duplicates(self):
        root = Folder.objects.create(owner=self.user, name="Root")
        child = Folder.objects.create(owner=self.user, parent=root, name="Child")
        other_parent = Folder.objects.create(owner=self.other, name="Other")

        root.parent = child
        with self.assertRaises(ValidationError):
            root.save()
        root.parent = None

        child.parent = other_parent
        with self.assertRaises(ValidationError):
            child.save()

        with self.assertRaises(ValidationError):
            Folder.objects.create(owner=self.user, name="Root")
        second_parent = Folder.objects.create(owner=self.user, name="Second")
        Folder.objects.create(owner=self.user, parent=second_parent, name="Child")

    def test_folder_delete_requires_empty_and_does_not_change_quota(self):
        parent = Folder.objects.create(owner=self.user, name="Parent")
        child = Folder.objects.create(owner=self.user, parent=parent, name="Child")
        self.user.used_bytes = 6
        self.user.save(update_fields=["used_bytes"])

        response = self.client.post(reverse("drive:folder_delete", args=[parent.pk]))
        self.assertRedirects(response, reverse("drive:home"))
        self.assertTrue(Folder.objects.filter(pk=parent.pk).exists())

        self.client.post(reverse("drive:folder_delete", args=[child.pk]))
        item = StoredFile.objects.create(
            owner=self.user,
            folder=parent,
            display_name="kept.txt",
            blob=SimpleUploadedFile("kept.txt", b"stored"),
            size=6,
        )
        self.client.post(reverse("drive:folder_delete", args=[parent.pk]))
        self.assertTrue(Folder.objects.filter(pk=parent.pk).exists())
        self.assertTrue(StoredFile.objects.filter(pk=item.pk).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 6)

        item.folder = None
        item.save(update_fields=["folder"])
        self.client.post(reverse("drive:folder_delete", args=[parent.pk]))
        self.assertFalse(Folder.objects.filter(pk=parent.pk).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.used_bytes, 6)

    def test_upload_can_target_owned_folder_but_not_foreign_folder(self):
        target = Folder.objects.create(owner=self.user, name="Uploads")
        response = self.client.post(
            reverse("drive:upload"),
            {"folder": target.pk, "files": SimpleUploadedFile("inside.txt", b"inside")},
        )
        self.assertRedirects(response, reverse("drive:folder", args=[target.pk]))
        self.assertEqual(StoredFile.objects.get(display_name="inside.txt").folder, target)

        foreign = Folder.objects.create(owner=self.other, name="Foreign")
        response = self.client.post(
            reverse("drive:upload"),
            {"folder": foreign.pk, "files": SimpleUploadedFile("blocked.txt", b"blocked")},
        )
        self.assertRedirects(response, reverse("drive:home"))
        self.assertFalse(StoredFile.objects.filter(display_name="blocked.txt").exists())

    @override_settings(UPLOAD_CHUNK_BYTES=1024, MAX_SINGLE_UPLOAD_BYTES=4096)
    def test_resumable_upload_keeps_target_folder_and_idempotency_payload(self):
        target = Folder.objects.create(owner=self.user, name="Chunks")
        payload = {"name": "inside.bin", "size": 3, "content_type": "application/octet-stream", "folder_id": target.pk}
        first = self.client.post(
            reverse("drive:upload_initiate"),
            json.dumps(payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="folder-upload",
        )
        self.assertEqual(first.status_code, 200)
        conflict = self.client.post(
            reverse("drive:upload_initiate"),
            json.dumps({**payload, "name": "other.bin"}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="folder-upload",
        )
        self.assertEqual(conflict.status_code, 409)
        upload_id = first.json()["upload_id"]
        body = b"abc"
        self.client.put(
            reverse("drive:upload_part", args=[upload_id, 0]),
            body,
            content_type="application/octet-stream",
            HTTP_X_CHUNK_SHA256=hashlib.sha256(body).hexdigest(),
        )
        self.assertEqual(self.client.post(reverse("drive:upload_complete", args=[upload_id])).status_code, 200)
        self.assertEqual(StoredFile.objects.get(display_name="inside.bin").folder, target)

    def test_favorites_remain_global_across_folders(self):
        folder = Folder.objects.create(owner=self.user, name="Folder")
        favorite = StoredFile.objects.create(
            owner=self.user,
            folder=folder,
            display_name="favorite.txt",
            blob=SimpleUploadedFile("favorite.txt", b"fav"),
            size=3,
            favorite=True,
        )
        response = self.client.get(reverse("drive:home"), {"view": "favorites"})
        self.assertEqual(list(response.context["files"]), [favorite])
        self.assertEqual(list(response.context["folders"]), [])

    def test_upload_uses_a_stable_dialog_instead_of_a_hidden_dropdown_form(self):
        response = self.client.get(reverse("drive:home"))
        self.assertContains(response, '<dialog id="upload-dialog"', html=False)
        self.assertContains(response, "data-upload-form", html=False)
        self.assertContains(response, "data-selected-files", html=False)
        self.assertContains(response, "data-drop-zone-title", html=False)
        self.assertNotContains(response, "data-upload-form hidden", html=False)

    def test_file_browser_offers_list_and_grid_views(self):
        Folder.objects.create(owner=self.user, name="Grid folder")
        response = self.client.get(reverse("drive:home"))
        self.assertContains(response, 'data-file-browser data-view="grid"', html=False)
        self.assertContains(response, 'data-view-mode="list"', html=False)
        self.assertContains(response, 'data-view-mode="grid"', html=False)
        self.assertContains(response, 'data-item-kind="folder"', html=False)

    def test_authenticated_shell_includes_dedicated_mobile_navigation(self):
        response = self.client.get(reverse("drive:home"))
        self.assertContains(response, 'class="mobile-header"', html=False)
        self.assertContains(response, 'class="mobile-nav"', html=False)
        self.assertContains(response, "dataset.deviceClass", html=False)
