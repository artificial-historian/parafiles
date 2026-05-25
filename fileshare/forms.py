from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.db.models import Q
from django.utils import timezone

from .models import (
    AbuseReport,
    Invitation,
    ModerationAction,
    PublicShare,
    QuotaOverride,
    RateLimitEvent,
    StoredFile,
    User,
)
from .services.email_verification import normalize_email
from .services.security import sanitize_filename


class InvitationRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    terms_accepted = forms.BooleanField(
        required=True,
        label="I have read and agree to the Terms of Service and Privacy Policy.",
    )
    age_confirmed = forms.BooleanField(
        required=True,
        label="I confirm that I am at least 16 years old.",
    )
    upload_review_consent = forms.BooleanField(
        required=True,
        label=(
            "I understand that uploads may be reviewed for abuse, malware, copyright "
            "infringement, or violations of law."
        ),
    )
    alpha_notice = forms.BooleanField(
        required=True,
        label=(
            "I understand that Parafiles is a free beta service, not a file locker "
            "or backup service, and that I must keep my own copies of uploaded data."
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self) -> str:
        email = normalize_email(self.cleaned_data["email"])
        if User.objects.filter(
            Q(email__iexact=email) | Q(pending_email__iexact=email)
        ).exists():
            raise forms.ValidationError("An account is already using this email address.")
        return email


class InvitationCreateForm(forms.ModelForm):
    expires_in_days = forms.IntegerField(min_value=1, max_value=365, initial=14)
    send_email = forms.BooleanField(required=False, initial=True)

    class Meta:
        model = Invitation
        fields = ("email",)

    def clean_email(self) -> str:
        return self.cleaned_data["email"].strip().lower()


class EmailDiagnosticForm(forms.Form):
    recipient = forms.EmailField()
    subject = forms.CharField(max_length=180, initial="Parafiles email diagnostic")
    body = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6}),
        initial=(
            "This is a Parafiles diagnostic email. If this message reached you, "
            "Django handed mail to the configured email backend successfully."
        ),
    )


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email",)

    def clean_email(self) -> str:
        email = normalize_email(self.cleaned_data.get("email"))
        if not email:
            return ""
        existing = User.objects.filter(
            Q(email__iexact=email) | Q(pending_email__iexact=email)
        ).exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("An account is already using this email address.")
        return email


class VerifiedEmailPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        email = normalize_email(email)
        user_model = get_user_model()
        users = user_model._default_manager.filter(email__iexact=email, is_active=True)
        return (
            user
            for user in users
            if user.has_usable_password()
            and user.has_verified_email
            and normalize_email(user.email) == email
        )


class TwoFactorTokenForm(forms.Form):
    token = forms.RegexField(
        regex=r"^\d{6,8}$",
        max_length=8,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
    )


class FolderForm(forms.Form):
    name = forms.CharField(max_length=180)

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise forms.ValidationError("Enter a folder name without path separators.")
        return name


class FileRenameForm(forms.Form):
    filename = forms.CharField(max_length=255)

    def clean_filename(self) -> str:
        return sanitize_filename(self.cleaned_data["filename"])


class FileMetadataForm(forms.ModelForm):
    class Meta:
        model = StoredFile
        fields = ("title", "description", "version", "game_version", "changelog")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "changelog": forms.Textarea(attrs={"rows": 4}),
        }


class UploadStartForm(forms.Form):
    folder_id = forms.IntegerField(required=False)
    filename = forms.CharField(max_length=255)
    size = forms.IntegerField(min_value=1)
    content_type = forms.CharField(max_length=255, required=False)
    sha256 = forms.RegexField(regex=r"^[A-Fa-f0-9]{64}$", required=False)
    upload_terms = forms.BooleanField(required=True)

    def clean_filename(self) -> str:
        return sanitize_filename(self.cleaned_data["filename"])


class MoveForm(forms.Form):
    target_folder_id = forms.IntegerField()


class AbuseReportForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = AbuseReport
        fields = ("category", "message", "contact_email")
        widgets = {
            "message": forms.Textarea(attrs={"rows": 5}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("website"):
            raise forms.ValidationError("Report rejected.")
        return cleaned


class ReportModerationForm(forms.ModelForm):
    class Meta:
        model = AbuseReport
        fields = ("status", "assigned_to", "staff_notes")
        widgets = {
            "staff_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(is_staff=True, is_active=True)
        self.fields["assigned_to"].required = False


class ShareSettingsForm(forms.ModelForm):
    clear_expiration = forms.BooleanField(required=False)

    class Meta:
        model = PublicShare
        fields = ("is_enabled", "expires_at")
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("clear_expiration"):
            cleaned["expires_at"] = None
        expires_at = cleaned.get("expires_at")
        if expires_at and expires_at <= timezone.now():
            raise forms.ValidationError("Expiration must be in the future.")
        return cleaned


class ModerationFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=255)
    report_status = forms.ChoiceField(
        required=False,
        choices=[("", "Any report status"), *AbuseReport.Status.choices],
    )
    file_status = forms.ChoiceField(
        required=False,
        choices=[("", "Any file status"), *StoredFile.Status.choices],
    )
    assigned_to = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        empty_label="Anyone",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(is_staff=True, is_active=True)


class ModerationBulkActionForm(forms.Form):
    TARGET_CHOICES = (
        ("reports", "Reports"),
        ("files", "Files"),
        ("folders", "Folders"),
    )
    target = forms.ChoiceField(choices=TARGET_CHOICES)
    action = forms.ChoiceField(choices=())
    ids = forms.CharField()
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    ACTIONS = {
        "reports": (
            (AbuseReport.Status.REVIEWING, "Mark reviewing"),
            (AbuseReport.Status.RESOLVED, "Resolve"),
            (AbuseReport.Status.REJECTED, "Reject"),
        ),
        "files": (
            ("hide", "Hide"),
            ("quarantine", "Quarantine"),
            ("restore", "Restore"),
            ("delete", "Delete"),
            ("rescan", "Rescan"),
        ),
        "folders": (
            ("hide", "Hide"),
            ("restore", "Restore"),
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        target = self.data.get("target") if self.is_bound else None
        actions = self.ACTIONS.get(target, ())
        self.fields["action"].choices = actions

    def clean_ids(self) -> list[int]:
        raw = self.cleaned_data["ids"]
        ids: list[int] = []
        for value in raw.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                ids.append(int(value))
            except ValueError as exc:
                raise forms.ValidationError("Invalid selected item.") from exc
        if not ids:
            raise forms.ValidationError("Select at least one item.")
        return ids


class ModerationActionFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=255)
    action = forms.ChoiceField(
        required=False,
        choices=[("", "Any action"), *ModerationAction.Action.choices],
    )
    actor = forms.ModelChoiceField(
        required=False,
        queryset=User.objects.none(),
        empty_label="Anyone",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["actor"].queryset = User.objects.filter(is_staff=True, is_active=True)


class RateLimitEventFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=255)
    scope = forms.CharField(required=False, max_length=64)
    action = forms.ChoiceField(
        required=False,
        choices=[("", "Any action"), *RateLimitEvent.Action.choices],
    )


class UserModerationFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=255)
    state = forms.ChoiceField(
        required=False,
        choices=(
            ("", "Any account state"),
            ("active", "Active"),
            ("inactive", "Suspended"),
            ("uploader", "Uploader enabled"),
            ("not_uploader", "Uploader disabled"),
            ("staff", "Staff"),
        ),
    )


class QuotaOverrideForm(forms.Form):
    storage_quota_gib = forms.DecimalField(
        required=False,
        min_value=Decimal("0.001"),
        max_digits=10,
        decimal_places=3,
        label="Storage quota (GiB)",
    )
    max_file_size_mib = forms.DecimalField(
        required=False,
        min_value=Decimal("0.001"),
        max_digits=10,
        decimal_places=3,
        label="Max file size (MiB)",
    )
    max_file_count = forms.IntegerField(required=False, min_value=1)
    folder_depth_limit = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, quota_override: QuotaOverride | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and quota_override:
            if quota_override.storage_quota_bytes is not None:
                self.initial["storage_quota_gib"] = Decimal(quota_override.storage_quota_bytes) / Decimal(
                    1024**3
                )
            if quota_override.max_file_size_bytes is not None:
                self.initial["max_file_size_mib"] = Decimal(
                    quota_override.max_file_size_bytes
                ) / Decimal(1024**2)
            self.initial["max_file_count"] = quota_override.max_file_count
            self.initial["folder_depth_limit"] = quota_override.folder_depth_limit

    def quota_values(self) -> dict[str, int | None]:
        def bytes_from_decimal(value: Decimal | None, multiplier: int) -> int | None:
            if value is None:
                return None
            return int(value * multiplier)

        return {
            "storage_quota_bytes": bytes_from_decimal(
                self.cleaned_data.get("storage_quota_gib"), 1024**3
            ),
            "max_file_size_bytes": bytes_from_decimal(
                self.cleaned_data.get("max_file_size_mib"), 1024**2
            ),
            "max_file_count": self.cleaned_data.get("max_file_count"),
            "folder_depth_limit": self.cleaned_data.get("folder_depth_limit"),
        }
