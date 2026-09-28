import uuid
from django.test import Client, TestCase
from . import tests as fixtures
encrypted = fixtures.encrypted
from .models import CipherFolder, CipherFile


class OrganizationTests(TestCase):
    setUp = fixtures.VaultAPITests.setUp
    create_vault = fixtures.VaultAPITests.create_vault
    upload = fixtures.VaultAPITests.upload
    reset_vault = fixtures.VaultAPITests.reset_vault
    def folder(self, parent=None, client=None):
        return (client or self.client).post('/api/cypher/folders/', {
            'id': str(uuid.uuid4()), 'vault_id': self.vault_id,
            'metadata': encrypted(), 'parent_id': parent,
        }, content_type='application/json')

    def change(self, identifier, data, kind='folders', client=None):
        return (client or self.client).patch(f'/api/cypher/items/{kind}/{identifier}/', data, content_type='application/json')

    def test_tree_cycles_owner_and_csrf(self):
        self.create_vault()
        self.create_vault(vault_id=str(uuid.uuid4()), client=self.other_client)
        first = self.folder().json()['folder']['id']
        second = self.folder(first).json()['folder']['id']
        self.assertEqual(self.change(first, {'parent_id': second}).status_code, 400)
        self.assertEqual(self.change(first, {'parent_id': first}).status_code, 400)
        self.assertEqual(self.change(first, {'starred': True}, client=self.other_client).status_code, 404)
        self.assertEqual(self.folder(first, client=self.other_client).status_code, 409)
        self.assertEqual(Client().get('/api/cypher/folders/').status_code, 401)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(self.change(first, {'starred': True}, client=csrf).status_code, 403)
        self.assertEqual(self.change(first, {'starred': 'yes'}).status_code, 400)

    def test_trash_restore_purge_and_quota(self):
        self.create_vault()
        folder = self.folder().json()['folder']['id']
        child = self.folder(folder).json()['folder']['id']
        file = self.upload().json()['file']['id']
        self.assertEqual(self.change(file, {'parent_id': child}, kind='files').status_code, 200)
        self.user.refresh_from_db(); used = self.user.used_bytes
        url = f'/api/cypher/items/folders/{folder}/'
        self.assertEqual(self.client.delete(url).status_code, 409)
        self.assertEqual(self.change(folder, {'trashed': True}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/cypher/files/{file}/download/').status_code, 409)
        self.assertEqual(self.folder(child).status_code, 400)
        self.user.refresh_from_db(); self.assertEqual(self.user.used_bytes, used)
        self.assertEqual(self.change(folder, {'trashed': False}).status_code, 200)
        response = self.client.get(f'/api/cypher/files/{file}/download/')
        self.assertEqual(response.status_code, 200)
        # Exhaust the test client's streaming wrapper, which closes the file
        # without closing the surrounding TestCase PostgreSQL transaction.
        self.assertEqual(b''.join(response.streaming_content), b'opaque ciphertext' * 2)
        self.change(folder, {'starred': True})
        self.assertTrue(CipherFolder.objects.get(pk=folder).starred)
        self.change(folder, {'trashed': True})
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertFalse(CipherFolder.objects.exists()); self.assertFalse(CipherFile.objects.exists())
        self.user.refresh_from_db(); self.assertEqual(self.user.used_bytes, 0)

    def test_independently_trashed_child_remains_trashed_and_restore_orphan(self):
        self.create_vault()
        parent = self.folder().json()['folder']['id']
        child = self.folder(parent).json()['folder']['id']
        self.change(child, {'trashed': True}); self.change(parent, {'trashed': True})
        self.change(parent, {'trashed': False})
        self.assertIsNotNone(CipherFolder.objects.get(pk=child).trashed_at)
        self.change(parent, {'trashed': True}); self.change(child, {'trashed': False})
        self.assertIsNone(CipherFolder.objects.get(pk=child).parent_id)

    def test_reset_removes_folder_metadata(self):
        self.create_vault(); parent = self.folder().json()['folder']['id']; self.folder(parent)
        self.assertEqual(self.reset_vault().status_code, 200)
        self.assertFalse(CipherFolder.objects.exists())

