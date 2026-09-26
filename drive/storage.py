from abc import ABC, abstractmethod

from .models import StoredFile


class StorageBackend(ABC):
    @abstractmethod
    def open(self, item):
        raise NotImplementedError

    @abstractmethod
    def delete(self, item):
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    def open(self, item):
        return item.blob.open("rb")

    def delete(self, item):
        return item.blob.delete(save=False)


class ExternalStorageBackend(StorageBackend):
    def open(self, item):
        raise RuntimeError(f"Storage backend {item.storage_backend!r} must provide a signed download or gateway stream")

    def delete(self, item):
        raise RuntimeError(f"Storage backend {item.storage_backend!r} must be deleted through the provider adapter")


def backend_for(item):
    if item.storage_backend == StoredFile.StorageBackend.LOCAL:
        return LocalStorageBackend()
    return ExternalStorageBackend()


def open_stored_file(item):
    return backend_for(item).open(item)


def delete_stored_file(item):
    return backend_for(item).delete(item)
