from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation, ValidationError
from django.utils import timezone

from fileshare.models import Folder, PublicShare, StoredFile, UploadSession, User
from fileshare.services.security import sanitize_filename


class UploadOffsetMismatch(ValidationError):
    pass


def ensure_storage_roots() -> None:
    settings.PARAFILES_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    settings.PARAFILES_UPLOAD_SESSION_ROOT.mkdir(parents=True, exist_ok=True)


def safe_join(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if root != candidate and root not in candidate.parents:
        raise SuspiciousOperation("Unsafe storage path.")
    return candidate


def temp_path_for_session(upload_id: uuid.UUID) -> Path:
    ensure_storage_roots()
    return safe_join(settings.PARAFILES_UPLOAD_SESSION_ROOT, f"{upload_id}.part")


def storage_key_for_file(user: User, filename: str) -> str:
    suffix = Path(sanitize_filename(filename)).suffix.lower()[:24]
    return f"files/{user.pk}/{uuid.uuid4().hex}{suffix}"


def private_path(storage_key: str) -> Path:
    return safe_join(settings.PARAFILES_STORAGE_ROOT, storage_key)


def write_chunk(session: UploadSession, chunk, expected_offset: int | None = None) -> None:
    if session.is_expired:
        session.status = UploadSession.Status.EXPIRED
        session.save(update_fields=["status"])
        raise ValidationError("Upload session expired.")
    if session.status not in {UploadSession.Status.INIT, UploadSession.Status.UPLOADING}:
        raise ValidationError("Upload session is not writable.")
    if expected_offset is not None and expected_offset != session.bytes_received:
        raise UploadOffsetMismatch(
            f"Upload offset mismatch. Expected {session.bytes_received}, got {expected_offset}."
        )

    path = safe_join(settings.PARAFILES_UPLOAD_SESSION_ROOT, session.temp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as destination:
        for piece in getattr(chunk, "chunks", lambda: [chunk])():
            destination.write(piece)
            session.bytes_received += len(piece)
            if session.bytes_received > session.size:
                session.status = UploadSession.Status.FAILED
                session.save(update_fields=["bytes_received", "status"])
                raise ValidationError("Uploaded bytes exceed the declared file size.")
    session.status = UploadSession.Status.UPLOADING
    session.save(update_fields=["bytes_received", "status"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finalize_session(session: UploadSession) -> StoredFile:
    if session.is_expired:
        session.status = UploadSession.Status.EXPIRED
        session.save(update_fields=["status"])
        raise ValidationError("Upload session expired.")
    if session.status not in {UploadSession.Status.INIT, UploadSession.Status.UPLOADING}:
        raise ValidationError("Upload session cannot be finalized.")
    if session.bytes_received != session.size:
        raise ValidationError("Upload is incomplete.")

    temp_path = safe_join(settings.PARAFILES_UPLOAD_SESSION_ROOT, session.temp_path)
    actual_size = temp_path.stat().st_size
    if actual_size != session.size:
        raise ValidationError("Uploaded byte count does not match the staged file size.")
    digest = sha256_file(temp_path)
    if session.sha256_expected and session.sha256_expected.lower() != digest:
        session.status = UploadSession.Status.FAILED
        session.save(update_fields=["status"])
        raise ValidationError("SHA-256 checksum mismatch.")

    storage_key = storage_key_for_file(session.owner, session.original_filename)
    final_path = private_path(storage_key)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(temp_path, final_path)
    except OSError:
        shutil.copyfile(temp_path, final_path)
        try:
            temp_path.unlink()
        except OSError:
            pass
    if os.name != "nt":
        os.chmod(final_path, 0o640)

    stored_file = StoredFile.objects.create(
        owner=session.owner,
        folder=session.folder,
        original_filename=sanitize_filename(session.original_filename),
        storage_key=storage_key,
        size=session.size,
        content_type=session.content_type,
        sha256=digest,
        status=StoredFile.Status.SCANNING,
    )
    session.status = UploadSession.Status.FINALIZED
    session.finalized_file = stored_file
    session.save(update_fields=["status", "finalized_file"])
    return stored_file


def purge_file_bytes(stored_file: StoredFile) -> None:
    path = private_path(stored_file.storage_key)
    try:
        try:
            os.chmod(path, 0o660)
        except OSError:
            pass
        path.unlink()
    except PermissionError:
        try:
            with path.open("r+b") as handle:
                handle.truncate(0)
        except OSError:
            pass
    except FileNotFoundError:
        pass
    stored_file.status = StoredFile.Status.DELETED
    stored_file.deleted_at = timezone.now()
    stored_file.save(update_fields=["status", "deleted_at", "updated_at"])


def folder_descendants(folder: Folder) -> list[Folder]:
    folders = [folder]
    queue = [folder]
    while queue:
        current = queue.pop(0)
        children = list(current.children.all())
        folders.extend(children)
        queue.extend(children)
    return folders


def purge_folder_tree(folder: Folder) -> None:
    folders = folder_descendants(folder)
    folder_ids = [item.pk for item in folders]
    for stored_file in StoredFile.objects.filter(folder_id__in=folder_ids).exclude(
        status=StoredFile.Status.DELETED
    ):
        purge_file_bytes(stored_file)
    now = timezone.now()
    Folder.objects.filter(pk__in=folder_ids).update(is_deleted=True, deleted_at=now, updated_at=now)
    PublicShare.objects.filter(folder_id__in=folder_ids).update(is_enabled=False)
    PublicShare.objects.filter(stored_file__folder_id__in=folder_ids).update(is_enabled=False)
