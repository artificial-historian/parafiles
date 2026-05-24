from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum

from fileshare.models import StoredFile, User


@dataclass(frozen=True)
class EffectiveQuota:
    storage_quota_bytes: int
    max_file_size_bytes: int
    max_file_count: int
    folder_depth_limit: int


def effective_quota(user: User) -> EffectiveQuota:
    override = getattr(user, "quota_override", None)

    def choose(field: str, default: int) -> int:
        if override:
            value = getattr(override, field, None)
            if value is not None:
                return value
        value = getattr(user, field, None)
        if value is not None:
            return value
        return default

    return EffectiveQuota(
        storage_quota_bytes=choose("storage_quota_bytes", settings.PARAFILES_DEFAULT_QUOTA_BYTES),
        max_file_size_bytes=choose(
            "max_file_size_bytes", settings.PARAFILES_DEFAULT_MAX_FILE_SIZE_BYTES
        ),
        max_file_count=choose("max_file_count", settings.PARAFILES_DEFAULT_MAX_FILE_COUNT),
        folder_depth_limit=choose(
            "folder_depth_limit", settings.PARAFILES_DEFAULT_MAX_FOLDER_DEPTH
        ),
    )


def storage_used(user: User) -> int:
    total = (
        StoredFile.objects.filter(owner=user)
        .exclude(status=StoredFile.Status.DELETED)
        .aggregate(total=Sum("size"))
        .get("total")
    )
    return int(total or 0)


def file_count(user: User) -> int:
    return StoredFile.objects.filter(owner=user).exclude(status=StoredFile.Status.DELETED).count()


def validate_upload_allowed(user: User, size: int) -> None:
    quota = effective_quota(user)
    if size <= 0:
        raise ValidationError("Upload size must be greater than zero.")
    if size > quota.max_file_size_bytes:
        raise ValidationError("This file is larger than your per-file upload limit.")
    if storage_used(user) + size > quota.storage_quota_bytes:
        raise ValidationError("This upload would exceed your storage quota.")
    if file_count(user) >= quota.max_file_count:
        raise ValidationError("This upload would exceed your file count limit.")
