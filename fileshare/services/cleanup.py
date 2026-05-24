from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.utils import timezone

from fileshare.models import UploadSession
from fileshare.services.storage import ensure_storage_roots, safe_join


@dataclass
class UploadCleanupResult:
    expired_sessions: int = 0
    temp_files_deleted: int = 0
    orphan_temp_files_deleted: int = 0
    bytes_deleted: int = 0


def remove_file(path: Path) -> int:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return 0
    try:
        path.unlink()
    except PermissionError:
        try:
            with path.open("r+b") as handle:
                handle.truncate(0)
        except OSError:
            return 0
    except OSError:
        return 0
    return size


def cleanup_expired_uploads(
    *,
    now=None,
    orphan_age_seconds: int | None = None,
) -> UploadCleanupResult:
    ensure_storage_roots()
    result = UploadCleanupResult()
    now = now or timezone.now()
    if orphan_age_seconds is None:
        orphan_age_seconds = settings.PARAFILES_UPLOAD_STAGING_RETENTION_SECONDS

    expirable_statuses = [
        UploadSession.Status.INIT,
        UploadSession.Status.UPLOADING,
        UploadSession.Status.FAILED,
        UploadSession.Status.EXPIRED,
    ]
    expired_sessions = UploadSession.objects.filter(
        expires_at__lte=now,
        status__in=expirable_statuses,
    )
    for session in expired_sessions:
        if session.status != UploadSession.Status.EXPIRED:
            session.status = UploadSession.Status.EXPIRED
            session.save(update_fields=["status"])
            result.expired_sessions += 1
        if session.temp_path:
            try:
                temp_path = safe_join(settings.PARAFILES_UPLOAD_SESSION_ROOT, session.temp_path)
            except SuspiciousOperation:
                continue
            deleted = remove_file(temp_path)
            if deleted:
                result.temp_files_deleted += 1
                result.bytes_deleted += deleted

    active_temp_paths = set(
        UploadSession.objects.exclude(
            status__in=[
                UploadSession.Status.EXPIRED,
                UploadSession.Status.FAILED,
                UploadSession.Status.FINALIZED,
            ]
        ).values_list("temp_path", flat=True)
    )
    cutoff = now - timedelta(seconds=orphan_age_seconds)
    root = settings.PARAFILES_UPLOAD_SESSION_ROOT
    for path in root.rglob("*.part"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).replace(os.sep, "/")
        if relative in active_temp_paths:
            continue
        modified_at = timezone.datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.get_current_timezone())
        if modified_at > cutoff:
            continue
        deleted = remove_file(path)
        if deleted:
            result.orphan_temp_files_deleted += 1
            result.bytes_deleted += deleted
    return result
