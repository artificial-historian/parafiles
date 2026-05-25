from __future__ import annotations

import secrets
import uuid
from datetime import timedelta
from pathlib import PurePosixPath

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


def public_slug() -> str:
    return secrets.token_urlsafe(24)


def invite_token() -> str:
    return secrets.token_urlsafe(32)


def invitation_expiry():
    return timezone.now() + timedelta(days=14)


class User(AbstractUser):
    verified_email = models.EmailField(blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    pending_email = models.EmailField(blank=True)
    is_uploader = models.BooleanField(default=False)
    storage_quota_bytes = models.BigIntegerField(null=True, blank=True)
    max_file_size_bytes = models.BigIntegerField(null=True, blank=True)
    max_file_count = models.PositiveIntegerField(null=True, blank=True)
    folder_depth_limit = models.PositiveIntegerField(null=True, blank=True)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("verified_email"),
                condition=~Q(verified_email=""),
                name="unique_verified_email_ci",
            )
        ]

    @property
    def has_verified_email(self) -> bool:
        return bool(
            self.email
            and self.verified_email
            and self.email.strip().lower() == self.verified_email.strip().lower()
            and self.email_verified_at
        )

    @property
    def can_upload(self) -> bool:
        return self.is_active and (self.is_uploader or self.is_staff or self.is_superuser)


class Invitation(models.Model):
    token = models.CharField(max_length=96, unique=True, default=invite_token)
    email = models.EmailField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=invitation_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invitations",
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()

    def accept(self, user: User) -> None:
        if not self.is_usable:
            raise ValidationError("This invitation is no longer valid.")
        self.accepted_at = timezone.now()
        self.accepted_by = user
        self.save(update_fields=["accepted_at", "accepted_by"])

    def __str__(self) -> str:
        return self.email or self.token


class Folder(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="folders")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    name = models.CharField(max_length=180, blank=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "parent", "name"],
                condition=Q(is_deleted=False),
                name="unique_live_folder_name_per_parent",
            )
        ]

    def clean(self) -> None:
        if self.parent and self.parent.owner_id != self.owner_id:
            raise ValidationError("Parent folder must belong to the same owner.")
        if self.parent_id and self.parent_id == self.id:
            raise ValidationError("A folder cannot be its own parent.")
        if self.name in {".", ".."} or "/" in self.name or "\\" in self.name:
            raise ValidationError("Folder names cannot contain path separators.")

    @classmethod
    def get_root(cls, owner: User) -> "Folder":
        folder, _created = cls.objects.get_or_create(owner=owner, parent=None, name="")
        return folder

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def depth(self) -> int:
        depth = 0
        parent = self.parent
        while parent:
            depth += 1
            parent = parent.parent
        return depth

    @property
    def display_name(self) -> str:
        return "/" if self.is_root else self.name

    @property
    def has_deleted_ancestor(self) -> bool:
        parent = self.parent
        while parent:
            if parent.is_deleted:
                return True
            parent = parent.parent
        return False

    @property
    def is_publicly_visible(self) -> bool:
        return not self.is_deleted and not self.has_deleted_ancestor

    def path_parts(self) -> list[str]:
        parts: list[str] = []
        folder: Folder | None = self
        while folder and not folder.is_root:
            parts.append(folder.name)
            folder = folder.parent
        return list(reversed(parts))

    def logical_path(self) -> str:
        return "/" + str(PurePosixPath(*self.path_parts())) if self.path_parts() else "/"

    def contains(self, other: "Folder") -> bool:
        current: Folder | None = other
        while current:
            if current.pk == self.pk:
                return True
            current = current.parent
        return False

    def soft_delete(self) -> None:
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def __str__(self) -> str:
        return f"{self.owner}: {self.logical_path()}"


class StoredFile(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SCANNING = "scanning", "Scanning"
        AVAILABLE = "available", "Available"
        REVIEW = "review", "Needs review"
        QUARANTINED = "quarantined", "Quarantined"
        HIDDEN = "hidden", "Hidden"
        DELETED = "deleted", "Deleted"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="files")
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="files")
    original_filename = models.CharField(max_length=255)
    title = models.CharField(max_length=180, blank=True)
    description = models.TextField(blank=True)
    version = models.CharField(max_length=80, blank=True)
    game_version = models.CharField(max_length=80, blank=True)
    changelog = models.TextField(blank=True)
    storage_key = models.CharField(max_length=512, unique=True)
    size = models.BigIntegerField()
    content_type = models.CharField(max_length=255, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    scan_completed_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["original_filename", "id"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["sha256"]),
        ]

    @property
    def is_publicly_downloadable(self) -> bool:
        return (
            self.status == self.Status.AVAILABLE
            and self.deleted_at is None
            and self.folder.is_publicly_visible
        )

    def hide(self) -> None:
        self.status = self.Status.HIDDEN
        self.disabled_at = timezone.now()
        self.save(update_fields=["status", "disabled_at", "updated_at"])

    def quarantine(self) -> None:
        self.status = self.Status.QUARANTINED
        self.disabled_at = timezone.now()
        self.save(update_fields=["status", "disabled_at", "updated_at"])

    def restore(self) -> None:
        self.status = self.Status.AVAILABLE
        self.disabled_at = None
        self.save(update_fields=["status", "disabled_at", "updated_at"])

    def soft_delete(self) -> None:
        self.status = self.Status.DELETED
        self.deleted_at = timezone.now()
        self.save(update_fields=["status", "deleted_at", "updated_at"])

    def __str__(self) -> str:
        return self.original_filename

    @property
    def display_title(self) -> str:
        return self.title or self.original_filename


class UploadSession(models.Model):
    class Status(models.TextChoices):
        INIT = "init", "Initialized"
        UPLOADING = "uploading", "Uploading"
        FINALIZED = "finalized", "Finalized"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions")
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="upload_sessions")
    upload_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    token = models.CharField(max_length=96, unique=True, default=invite_token)
    original_filename = models.CharField(max_length=255)
    size = models.BigIntegerField()
    content_type = models.CharField(max_length=255, blank=True)
    sha256_expected = models.CharField(max_length=64, blank=True)
    temp_path = models.CharField(max_length=512)
    bytes_received = models.BigIntegerField(default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.INIT)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    finalized_file = models.ForeignKey(
        StoredFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="upload_sessions"
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.status})"


class ScanResult(models.Model):
    class Engine(models.TextChoices):
        CLAMAV = "clamav", "ClamAV"
        VIRUSTOTAL_HASH = "virustotal_hash", "VirusTotal hash"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        CLEAN = "clean", "Clean"
        MALICIOUS = "malicious", "Malicious"
        SUSPICIOUS = "suspicious", "Suspicious"
        ERROR = "error", "Error"
        SKIPPED = "skipped", "Skipped"

    stored_file = models.ForeignKey(StoredFile, on_delete=models.CASCADE, related_name="scan_results")
    engine = models.CharField(max_length=32, choices=Engine.choices)
    status = models.CharField(max_length=32, choices=Status.choices)
    signature = models.CharField(max_length=255, blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PublicShare(models.Model):
    class TargetType(models.TextChoices):
        FILE = "file", "File"
        FOLDER = "folder", "Folder"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="public_shares")
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    stored_file = models.ForeignKey(
        StoredFile, on_delete=models.CASCADE, null=True, blank=True, related_name="public_shares"
    )
    folder = models.ForeignKey(
        Folder, on_delete=models.CASCADE, null=True, blank=True, related_name="public_shares"
    )
    slug = models.CharField(max_length=96, unique=True, default=public_slug)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    regenerated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["slug", "is_enabled"])]

    def clean(self) -> None:
        has_file = self.stored_file_id is not None
        has_folder = self.folder_id is not None
        if has_file == has_folder:
            raise ValidationError("A share must target exactly one file or folder.")
        if self.target_type == self.TargetType.FILE and not has_file:
            raise ValidationError("File shares must target a file.")
        if self.target_type == self.TargetType.FOLDER and not has_folder:
            raise ValidationError("Folder shares must target a folder.")

    @property
    def is_live(self) -> bool:
        return self.is_enabled and (self.expires_at is None or self.expires_at > timezone.now())

    @property
    def target(self) -> StoredFile | Folder:
        return self.stored_file if self.stored_file_id else self.folder

    def regenerate_slug(self) -> None:
        self.slug = public_slug()
        self.regenerated_at = timezone.now()
        self.save(update_fields=["slug", "regenerated_at"])

    def __str__(self) -> str:
        return f"{self.target_type}:{self.slug}"


class AbuseReport(models.Model):
    class Category(models.TextChoices):
        MALWARE = "malware", "Malware"
        COPYRIGHT = "copyright", "Copyright"
        HARASSMENT = "harassment", "Harassment"
        ILLEGAL = "illegal", "Illegal content"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWING = "reviewing", "Reviewing"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"

    share = models.ForeignKey(PublicShare, on_delete=models.SET_NULL, null=True, related_name="abuse_reports")
    stored_file = models.ForeignKey(
        StoredFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="abuse_reports"
    )
    folder = models.ForeignKey(
        Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="abuse_reports"
    )
    category = models.CharField(max_length=32, choices=Category.choices)
    message = models.TextField()
    contact_email = models.EmailField(blank=True)
    reporter_ip_hash = models.CharField(max_length=64)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_abuse_reports",
    )
    staff_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-created_at"]


class ModerationAction(models.Model):
    class Action(models.TextChoices):
        HIDE = "hide", "Hide"
        QUARANTINE = "quarantine", "Quarantine"
        RESTORE = "restore", "Restore"
        DELETE = "delete", "Delete"
        PURGE = "purge", "Purge"
        RESCAN = "rescan", "Rescan"
        REGENERATE_SHARE = "regenerate_share", "Regenerate share"
        RESOLVE_REPORT = "resolve_report", "Resolve report"
        SUSPEND_USER = "suspend_user", "Suspend user"
        RESTORE_USER = "restore_user", "Restore user"
        DISABLE_UPLOADS = "disable_uploads", "Disable uploads"
        DISABLE_USER_SHARES = "disable_user_shares", "Disable user shares"
        UPDATE_QUOTA = "update_quota", "Update quota"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="moderation_actions"
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    stored_file = models.ForeignKey(
        StoredFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="moderation_actions"
    )
    folder = models.ForeignKey(
        Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="moderation_actions"
    )
    share = models.ForeignKey(
        PublicShare, on_delete=models.SET_NULL, null=True, blank=True, related_name="moderation_actions"
    )
    report = models.ForeignKey(
        AbuseReport, on_delete=models.SET_NULL, null=True, blank=True, related_name="moderation_actions"
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="targeted_moderation_actions",
    )
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DownloadEvent(models.Model):
    class Outcome(models.TextChoices):
        ALLOWED = "allowed", "Allowed"
        RATE_LIMITED = "rate_limited", "Rate limited"
        DENIED = "denied", "Denied"
        NOT_FOUND = "not_found", "Not found"

    stored_file = models.ForeignKey(
        StoredFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="download_events"
    )
    share = models.ForeignKey(
        PublicShare, on_delete=models.SET_NULL, null=True, blank=True, related_name="download_events"
    )
    ip_hash = models.CharField(max_length=64)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    bytes_served = models.BigIntegerField(default=0)
    outcome = models.CharField(max_length=32, choices=Outcome.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_at", "outcome"])]


class QuotaOverride(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quota_override")
    storage_quota_bytes = models.BigIntegerField(null=True, blank=True)
    max_file_size_bytes = models.BigIntegerField(null=True, blank=True)
    max_file_count = models.PositiveIntegerField(null=True, blank=True)
    folder_depth_limit = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Quota override for {self.user}"


class RateLimitEvent(models.Model):
    class Action(models.TextChoices):
        WARN = "warn", "Warn"
        SLOW = "slow", "Slow"
        BLOCK = "block", "Block"

    scope = models.CharField(max_length=64)
    key = models.CharField(max_length=160)
    ip_hash = models.CharField(max_length=64, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    count = models.PositiveIntegerField(default=0)
    action = models.CharField(max_length=16, choices=Action.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
