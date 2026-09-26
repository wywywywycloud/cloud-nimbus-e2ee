"""Run explicitly against the disposable CI PostgreSQL service, never production."""
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from vaults.models import Vault


class PostgreSQLInvariants(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL service required")
        self.owner = get_user_model().objects.create_user(username="pg-lock-owner")
        self.vault = Vault.objects.create(owner=self.owner)

    def test_partial_unique_index_preserves_revoked_generations(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Vault.objects.create(owner=self.owner)
        Vault.objects.filter(pk=self.vault.pk).update(revoked_at=timezone.now())
        replacement = Vault.objects.create(owner=self.owner)
        self.assertNotEqual(replacement.pk, self.vault.pk)
        self.assertIsNotNone(Vault.objects.get(pk=self.vault.pk).revoked_at)

    def test_vault_lock_excludes_a_concurrent_writer(self):
        def contender():
            close_old_connections()
            try:
                with transaction.atomic():
                    Vault.objects.select_for_update(nowait=True).get(pk=self.vault.pk)
                return False
            except DatabaseError as exc:
                return getattr(exc.__cause__, "sqlstate", None) == "55P03"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Vault.objects.select_for_update().get(pk=self.vault.pk)
                self.assertTrue(pool.submit(contender).result(timeout=10))
