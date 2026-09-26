from collections import defaultdict

from django.db.models import Sum

from .models import Folder, StoredFile


def attach_folder_sizes(owner, folders):
    """Attach recursive byte totals to a collection of folders."""
    folder_list = list(folders)
    if not folder_list:
        return folder_list

    owner_id = getattr(owner, "pk", owner)
    parent_by_id = dict(
        Folder.objects.filter(owner_id=owner_id).values_list("pk", "parent_id")
    )
    direct_sizes = dict(
        StoredFile.objects.filter(owner_id=owner_id, folder_id__isnull=False)
        .values("folder_id")
        .annotate(total=Sum("size"))
        .values_list("folder_id", "total")
    )
    totals = defaultdict(int, direct_sizes)

    # Propagate each folder's direct file bytes through all of its ancestors.
    # A seen set keeps the read path safe even if legacy data is malformed.
    for folder_id, size in direct_sizes.items():
        ancestor_id = parent_by_id.get(folder_id)
        seen = {folder_id}
        while ancestor_id and ancestor_id not in seen:
            totals[ancestor_id] += size
            seen.add(ancestor_id)
            ancestor_id = parent_by_id.get(ancestor_id)

    for folder in folder_list:
        folder.total_size_bytes = totals[folder.pk]
    return folder_list
