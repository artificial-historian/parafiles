from __future__ import annotations

import hashlib
import time
from base64 import b32encode
from datetime import timedelta
from urllib.parse import quote, urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, SuspiciousOperation, ValidationError
from django.core.cache import cache
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.db import connection
from django.db.models import Count, F, Q, Sum
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp import match_token, user_has_device
from django_otp.plugins.otp_totp.models import TOTPDevice

from .forms import (
    AbuseReportForm,
    AccountSettingsForm,
    EmailDiagnosticForm,
    FileMetadataForm,
    FileRenameForm,
    FolderForm,
    InvitationCreateForm,
    InvitationRegistrationForm,
    MoveForm,
    ModerationActionFilterForm,
    ModerationBulkActionForm,
    ModerationFilterForm,
    QuotaOverrideForm,
    RateLimitEventFilterForm,
    ReportModerationForm,
    TwoFactorTokenForm,
    UserModerationFilterForm,
    ShareSettingsForm,
    UploadStartForm,
)
from .models import (
    AbuseReport,
    DownloadEvent,
    Folder,
    Invitation,
    ModerationAction,
    PublicShare,
    QuotaOverride,
    RateLimitEvent,
    StoredFile,
    UploadSession,
    User,
)
from .services.moderation import record_action
from .services.health import operations_health
from .services.email_verification import (
    normalize_email,
    send_email_verification,
    unpack_email_verification_token,
    verified_email_is_taken,
)
from .services.invitations import invitation_url, send_invitation_email
from .services.quotas import effective_quota, file_count, storage_used, validate_upload_allowed
from .services.scanning import run_scan_for_file
from .services.security import content_disposition, request_ip_hash, request_user_agent_hash
from .services.storage import (
    UploadOffsetMismatch,
    ensure_signature_file,
    finalize_session,
    private_path,
    purge_file_bytes,
    signature_storage_key,
    purge_folder_tree,
    temp_path_for_session,
    write_chunk,
)
from .services.throttling import (
    check_download_request,
    check_public_page,
    check_report,
    release_download_slot,
)
from .services.tokens import create_download_token, load_download_token
from .tasks import scan_file_task


def wants_json(request: HttpRequest) -> bool:
    return "application/json" in request.headers.get("accept", "") or request.headers.get(
        "x-requested-with"
    ) == "XMLHttpRequest"


def redirect_target(request: HttpRequest, fallback: str) -> str:
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return fallback


def uploader_required(view_func):
    def wrapped(request: HttpRequest, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied
        if not request.user.can_upload:
            raise PermissionDenied("This account cannot upload files.")
        return view_func(request, *args, **kwargs)

    return wrapped


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "fileshare/home.html", legal_contact_context())


def legal_contact_context() -> dict[str, str]:
    return {
        "site_name": settings.PARAFILES_SITE_NAME,
        "contact_email": settings.PARAFILES_CONTACT_EMAIL,
        "abuse_email": settings.PARAFILES_ABUSE_EMAIL,
        "privacy_email": settings.PARAFILES_PRIVACY_EMAIL,
        "security_email": settings.PARAFILES_SECURITY_EMAIL,
    }


def terms(request: HttpRequest) -> HttpResponse:
    return render(request, "fileshare/legal_terms.html", legal_contact_context())


def privacy(request: HttpRequest) -> HttpResponse:
    return render(request, "fileshare/legal_privacy.html", legal_contact_context())


def cookies(request: HttpRequest) -> HttpResponse:
    return render(request, "fileshare/legal_cookies.html", legal_contact_context())


def copyright_abuse(request: HttpRequest) -> HttpResponse:
    return render(request, "fileshare/legal_copyright_abuse.html", legal_contact_context())


def contact(request: HttpRequest) -> HttpResponse:
    return render(request, "fileshare/contact.html", legal_contact_context())


def register_invite(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(Invitation, token=token)
    if not invitation.is_usable:
        return render(request, "fileshare/invite_invalid.html", status=410)
    verification_email = ""
    if request.method == "POST":
        form = InvitationRegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.email = form.cleaned_data["email"]
                if invitation.email and normalize_email(invitation.email) == normalize_email(
                    user.email
                ):
                    user.verified_email = normalize_email(user.email)
                    user.email_verified_at = timezone.now()
                else:
                    verification_email = user.email
                user.is_uploader = True
                user.save()
                Folder.get_root(user)
                invitation.accept(user)
            login(request, user)
            if verification_email:
                send_email_verification(request, user, verification_email)
                messages.success(
                    request,
                    "Account created. Check your email to verify the recovery address.",
                )
            return redirect("dashboard")
    else:
        form = InvitationRegistrationForm(initial={"email": invitation.email})
    return render(
        request,
        "fileshare/register_invite.html",
        {"form": form, "invitation": invitation},
    )


def verify_email(request: HttpRequest, token: str) -> HttpResponse:
    try:
        user_id, email = unpack_email_verification_token(token)
    except ValidationError:
        return render(request, "fileshare/email_verification_invalid.html", status=400)

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return render(request, "fileshare/email_verification_invalid.html", status=400)
    if verified_email_is_taken(email, user):
        messages.error(request, "This email address is already verified for another account.")
        return redirect("login")

    current_email = normalize_email(user.email)
    pending_email = normalize_email(user.pending_email)
    if pending_email == email:
        user.email = email
        user.verified_email = email
        user.email_verified_at = timezone.now()
        user.pending_email = ""
        user.save(
            update_fields=["email", "verified_email", "email_verified_at", "pending_email"]
        )
    elif current_email == email:
        user.verified_email = email
        user.email_verified_at = timezone.now()
        if pending_email == email:
            user.pending_email = ""
            user.save(update_fields=["verified_email", "email_verified_at", "pending_email"])
        else:
            user.save(update_fields=["verified_email", "email_verified_at"])
    else:
        return render(request, "fileshare/email_verification_invalid.html", status=400)

    messages.success(request, "Email address verified.")
    if request.user.is_authenticated and request.user.pk == user.pk:
        return redirect("account_settings")
    return redirect("login")


@require_POST
@login_required
def resend_email_verification(request: HttpRequest) -> HttpResponse:
    user = request.user
    email = normalize_email(user.pending_email or ("" if user.has_verified_email else user.email))
    if not email:
        messages.error(request, "There is no email address waiting for verification.")
    elif verified_email_is_taken(email, user):
        messages.error(request, "This email address is already verified for another account.")
    else:
        send_email_verification(request, user, email)
        messages.success(request, "Verification email sent.")
    return redirect("account_settings")


def owned_folder_or_404(user, folder_id: int | None) -> Folder:
    if folder_id:
        return get_object_or_404(Folder, pk=folder_id, owner=user, is_deleted=False)
    return Folder.get_root(user)


def owned_file_or_404(user, file_id: int) -> StoredFile:
    return get_object_or_404(
        StoredFile.objects.select_related("folder"),
        pk=file_id,
        owner=user,
    )


@login_required
@uploader_required
def dashboard(request: HttpRequest) -> HttpResponse:
    current_folder = owned_folder_or_404(request.user, request.GET.get("folder"))
    root = Folder.get_root(request.user)
    folders = Folder.objects.filter(owner=request.user, is_deleted=False).select_related("parent")
    child_folders = folders.filter(parent=current_folder)
    files = (
        StoredFile.objects.filter(owner=request.user, folder=current_folder)
        .exclude(status=StoredFile.Status.DELETED)
        .prefetch_related("public_shares")
    )
    shares = PublicShare.objects.filter(owner=request.user, is_enabled=True)
    quota = effective_quota(request.user)
    context = {
        "root": root,
        "current_folder": current_folder,
        "folders": folders,
        "child_folders": child_folders,
        "files": files,
        "shares": shares,
        "quota": quota,
        "used_bytes": storage_used(request.user),
        "folder_form": FolderForm(),
        "move_targets": folders,
    }
    return render(request, "fileshare/dashboard.html", context)


def folder_breadcrumbs(folder: Folder) -> list[Folder]:
    breadcrumbs: list[Folder] = []
    current: Folder | None = folder
    while current:
        breadcrumbs.append(current)
        current = current.parent
    return list(reversed(breadcrumbs))


def public_share_url(request: HttpRequest, share: PublicShare) -> str:
    if share.target_type == PublicShare.TargetType.FILE:
        url = reverse("public_file", args=[share.slug])
    else:
        url = reverse("public_folder", args=[share.slug])
    return request.build_absolute_uri(url)


def folder_move_targets(folders: list[Folder], folder: Folder) -> list[Folder]:
    return [
        candidate
        for candidate in folders
        if candidate.pk != folder.pk and not folder.contains(candidate)
    ]


def ordered_folder_tree(folders: list[Folder]) -> list[Folder]:
    children: dict[int | None, list[Folder]] = {}
    for folder in folders:
        children.setdefault(folder.parent_id, []).append(folder)
    for siblings in children.values():
        siblings.sort(key=lambda item: (item.name.lower(), item.pk))

    ordered: list[Folder] = []

    def visit(folder: Folder) -> None:
        ordered.append(folder)
        for child in children.get(folder.pk, []):
            visit(child)

    for root in children.get(None, []):
        visit(root)
    return ordered


@login_required
@uploader_required
def files_and_shares(request: HttpRequest) -> HttpResponse:
    current_folder = owned_folder_or_404(request.user, request.GET.get("folder"))
    folders = list(
        Folder.objects.filter(owner=request.user, is_deleted=False)
        .select_related("parent")
        .order_by("name", "id")
    )
    folder_tree = ordered_folder_tree(folders)
    child_folders = [folder for folder in folder_tree if folder.parent_id == current_folder.pk]
    files = list(
        StoredFile.objects.filter(owner=request.user, folder=current_folder)
        .exclude(status=StoredFile.Status.DELETED)
        .order_by("original_filename", "id")
    )
    active_shares = list(
        PublicShare.objects.filter(owner=request.user, is_enabled=True)
        .select_related("stored_file", "folder")
        .order_by("-created_at")
    )
    file_shares = {share.stored_file_id: share for share in active_shares if share.stored_file_id}
    folder_shares = {share.folder_id: share for share in active_shares if share.folder_id}
    folder_rows = [
        {
            "folder": folder,
            "share": folder_shares.get(folder.pk),
            "share_url": public_share_url(request, folder_shares[folder.pk])
            if folder.pk in folder_shares
            else "",
            "move_targets": folder_move_targets(folders, folder),
        }
        for folder in child_folders
    ]
    file_rows = [
        {
            "file": stored_file,
            "share": file_shares.get(stored_file.pk),
            "share_url": public_share_url(request, file_shares[stored_file.pk])
            if stored_file.pk in file_shares
            else "",
        }
        for stored_file in files
    ]
    share_rows = [
        {
            "share": share,
            "name": share.stored_file.original_filename
            if share.stored_file_id
            else share.folder.logical_path(),
            "url": public_share_url(request, share),
        }
        for share in active_shares
    ]
    context = {
        "current_folder": current_folder,
        "breadcrumbs": folder_breadcrumbs(current_folder),
        "folder_rows": folder_rows,
        "file_rows": file_rows,
        "folder_tree": folder_tree,
        "move_targets": folders,
        "share_rows": share_rows,
    }
    return render(request, "fileshare/files_and_shares.html", context)


@login_required
@uploader_required
def account_settings(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        user = request.user
        original_email = user.email
        original_verified_email = user.verified_email
        original_email_verified_at = user.email_verified_at
        current_email = normalize_email(original_email)
        pending_email = normalize_email(user.pending_email)
        had_verified_email = bool(
            current_email
            and normalize_email(original_verified_email) == current_email
            and original_email_verified_at
        )
        form = AccountSettingsForm(request.POST, instance=user)
        if form.is_valid():
            user.email = original_email
            user.verified_email = original_verified_email
            user.email_verified_at = original_email_verified_at
            new_email = form.cleaned_data["email"]

            if not new_email:
                user.email = ""
                user.verified_email = ""
                user.email_verified_at = None
                user.pending_email = ""
                user.save(
                    update_fields=[
                        "email",
                        "verified_email",
                        "email_verified_at",
                        "pending_email",
                    ]
                )
                messages.success(request, "Account email removed.")
            elif current_email == new_email:
                user.email = new_email
                if had_verified_email:
                    user.verified_email = new_email
                    user.save(update_fields=["email", "verified_email"])
                    messages.success(request, "Account settings updated.")
                else:
                    user.save(update_fields=["email"])
                    send_email_verification(request, user, new_email)
                    messages.success(request, "Verification email sent.")
            elif pending_email == new_email:
                send_email_verification(request, user, new_email)
                messages.success(request, "Verification email resent.")
            elif had_verified_email:
                user.pending_email = new_email
                user.save(update_fields=["pending_email"])
                send_email_verification(request, user, new_email)
                messages.success(
                    request,
                    (
                        "Verification email sent. Your current recovery email remains active "
                        "until the new address is verified."
                    ),
                )
            else:
                user.email = new_email
                user.verified_email = ""
                user.email_verified_at = None
                user.pending_email = ""
                user.save(
                    update_fields=[
                        "email",
                        "verified_email",
                        "email_verified_at",
                        "pending_email",
                    ]
                )
                send_email_verification(request, user, new_email)
                messages.success(request, "Verification email sent.")
            return redirect("account_settings")
    else:
        form = AccountSettingsForm(
            instance=request.user,
            initial={"email": request.user.pending_email or request.user.email},
        )

    quota = effective_quota(request.user)
    shares = (
        PublicShare.objects.filter(owner=request.user)
        .select_related("stored_file", "folder")
        .order_by("-created_at")
    )
    recent_downloads = (
        DownloadEvent.objects.filter(stored_file__owner=request.user)
        .select_related("stored_file", "share")
        .order_by("-created_at")[:20]
    )
    recent_scans = (
        StoredFile.objects.filter(owner=request.user)
        .exclude(status=StoredFile.Status.DELETED)
        .prefetch_related("scan_results")
        .order_by("-updated_at")[:20]
    )
    context = {
        "form": form,
        "quota": quota,
        "used_bytes": storage_used(request.user),
        "file_count": file_count(request.user),
        "folder_count": Folder.objects.filter(owner=request.user, is_deleted=False).count(),
        "shares": shares,
        "recent_downloads": recent_downloads,
        "recent_scans": recent_scans,
        "has_verified_email": request.user.has_verified_email,
    }
    return render(request, "fileshare/account_settings.html", context)


@login_required
@uploader_required
def quick_share(request: HttpRequest) -> HttpResponse:
    root = Folder.get_root(request.user)
    return render(
        request,
        "fileshare/quick_share.html",
        {
            "root_folder": root,
        },
    )


def folder_json(folder: Folder) -> dict[str, object]:
    return {
        "id": folder.pk,
        "parent_id": folder.parent_id,
        "name": folder.display_name,
        "path": folder.logical_path(),
        "depth": folder.depth,
    }


@login_required
@uploader_required
def quick_share_folders(request: HttpRequest) -> JsonResponse:
    folders = (
        Folder.objects.filter(owner=request.user, is_deleted=False)
        .select_related("parent")
        .order_by("parent_id", "name", "id")
    )
    return JsonResponse({"folders": [folder_json(folder) for folder in folders]})


@require_POST
@login_required
@uploader_required
def quick_share_upload_folder(request: HttpRequest, upload_id) -> JsonResponse:
    session = upload_session_or_404(request, upload_id)
    target = owned_folder_or_404(request.user, request.POST.get("folder_id"))
    if session.status not in {UploadSession.Status.INIT, UploadSession.Status.UPLOADING}:
        return JsonResponse({"errors": ["Upload folder can no longer be changed."]}, status=400)
    session.folder = target
    session.save(update_fields=["folder"])
    return JsonResponse({"folder": folder_json(target)})


@require_POST
@login_required
@uploader_required
def quick_share_file_folder(request: HttpRequest, file_id: int) -> JsonResponse:
    stored_file = owned_file_or_404(request.user, file_id)
    target = owned_folder_or_404(request.user, request.POST.get("folder_id"))
    stored_file.folder = target
    stored_file.save(update_fields=["folder", "updated_at"])
    return JsonResponse({"folder": folder_json(target)})


@require_POST
@login_required
@uploader_required
def quick_share_cancel_upload(request: HttpRequest, upload_id) -> JsonResponse:
    session = upload_session_or_404(request, upload_id)
    if session.status in {UploadSession.Status.INIT, UploadSession.Status.UPLOADING}:
        session.status = UploadSession.Status.FAILED
        session.save(update_fields=["status"])
        try:
            temp_path_for_session(session.upload_id).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return JsonResponse({"status": session.status})


def staff_user_required(request: HttpRequest) -> None:
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.is_staff:
        raise PermissionDenied("Two-factor authentication is only required for staff accounts.")


def staff_totp_setup_device(user) -> TOTPDevice:
    device = (
        TOTPDevice.objects.filter(user=user, confirmed=False, name="staff")
        .order_by("-id")
        .first()
    )
    if device:
        return device
    return TOTPDevice.objects.create(user=user, name="staff", confirmed=False)


@login_required
def staff_2fa_setup(request: HttpRequest) -> HttpResponse:
    staff_user_required(request)
    if user_has_device(request.user):
        return redirect(redirect_target(request, reverse("staff_2fa_verify")))

    device = staff_totp_setup_device(request.user)
    if request.method == "POST":
        form = TwoFactorTokenForm(request.POST)
        if form.is_valid() and device.verify_token(form.cleaned_data["token"]):
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            otp_login(request, device)
            messages.success(request, "Two-factor authentication enabled.")
            return redirect(redirect_target(request, reverse("moderation_dashboard")))
        messages.error(request, "Invalid two-factor code.")
    else:
        form = TwoFactorTokenForm()

    secret = b32encode(device.bin_key).decode("ascii")
    return render(
        request,
        "fileshare/staff_2fa_setup.html",
        {"form": form, "device": device, "secret": secret},
    )


@login_required
def staff_2fa_verify(request: HttpRequest) -> HttpResponse:
    staff_user_required(request)
    is_verified = getattr(request.user, "is_verified", lambda: False)
    if is_verified():
        return redirect(redirect_target(request, reverse("moderation_dashboard")))
    if not user_has_device(request.user):
        target = reverse("staff_2fa_setup")
        if request.GET.get("next"):
            target = f"{target}?{urlencode({'next': request.GET['next']})}"
        return redirect(target)

    if request.method == "POST":
        form = TwoFactorTokenForm(request.POST)
        if form.is_valid():
            device = match_token(request.user, form.cleaned_data["token"])
            if device:
                otp_login(request, device)
                return redirect(redirect_target(request, reverse("moderation_dashboard")))
        messages.error(request, "Invalid two-factor code.")
    else:
        form = TwoFactorTokenForm()
    return render(request, "fileshare/staff_2fa_verify.html", {"form": form})


@require_POST
@login_required
@uploader_required
def folder_create(request: HttpRequest) -> HttpResponse:
    parent = owned_folder_or_404(request.user, request.POST.get("parent_id"))
    fallback = f"{reverse('dashboard')}?folder={parent.pk}"
    quota = effective_quota(request.user)
    if parent.depth + 1 > quota.folder_depth_limit:
        raise ValidationError("This folder would exceed your folder depth limit.")
    form = FolderForm(request.POST)
    if form.is_valid():
        folder = Folder.objects.create(owner=request.user, parent=parent, name=form.cleaned_data["name"])
        if wants_json(request):
            return JsonResponse({"id": folder.pk, "name": folder.name})
        messages.success(request, "Folder created.")
    elif wants_json(request):
        return JsonResponse({"errors": form.errors}, status=400)
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def folder_rename(request: HttpRequest, folder_id: int) -> HttpResponse:
    folder = owned_folder_or_404(request.user, folder_id)
    fallback = f"{reverse('dashboard')}?folder={folder.parent_id or folder.pk}"
    if folder.is_root:
        raise PermissionDenied("The root folder cannot be renamed.")
    form = FolderForm(request.POST)
    if form.is_valid():
        folder.name = form.cleaned_data["name"]
        folder.full_clean()
        folder.save(update_fields=["name", "updated_at"])
        messages.success(request, "Folder renamed.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def folder_move(request: HttpRequest, folder_id: int) -> HttpResponse:
    folder = owned_folder_or_404(request.user, folder_id)
    fallback = f"{reverse('dashboard')}?folder={folder.parent_id}"
    if folder.is_root:
        raise PermissionDenied("The root folder cannot be moved.")
    form = MoveForm(request.POST)
    if form.is_valid():
        target = owned_folder_or_404(request.user, form.cleaned_data["target_folder_id"])
        if folder.contains(target):
            raise ValidationError("A folder cannot be moved into itself.")
        folder.parent = target
        folder.full_clean()
        folder.save(update_fields=["parent", "updated_at"])
        fallback = f"{reverse('dashboard')}?folder={folder.parent_id}"
        messages.success(request, "Folder moved.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def folder_delete(request: HttpRequest, folder_id: int) -> HttpResponse:
    folder = owned_folder_or_404(request.user, folder_id)
    fallback = f"{reverse('dashboard')}?folder={folder.parent_id}"
    if folder.is_root:
        raise PermissionDenied("The root folder cannot be deleted.")
    folder.soft_delete()
    messages.success(request, "Folder hidden from your dashboard.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def file_rename(request: HttpRequest, file_id: int) -> HttpResponse:
    stored_file = owned_file_or_404(request.user, file_id)
    fallback = f"{reverse('dashboard')}?folder={stored_file.folder_id}"
    form = FileRenameForm(request.POST)
    if form.is_valid():
        stored_file.original_filename = form.cleaned_data["filename"]
        stored_file.save(update_fields=["original_filename", "updated_at"])
        messages.success(request, "File renamed.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def file_metadata(request: HttpRequest, file_id: int) -> HttpResponse:
    stored_file = owned_file_or_404(request.user, file_id)
    fallback = f"{reverse('dashboard')}?folder={stored_file.folder_id}"
    form = FileMetadataForm(request.POST, instance=stored_file)
    if form.is_valid():
        form.save()
        messages.success(request, "File metadata updated.")
    else:
        messages.error(request, "File metadata update failed.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def file_move(request: HttpRequest, file_id: int) -> HttpResponse:
    stored_file = owned_file_or_404(request.user, file_id)
    fallback = f"{reverse('dashboard')}?folder={stored_file.folder_id}"
    form = MoveForm(request.POST)
    if form.is_valid():
        target = owned_folder_or_404(request.user, form.cleaned_data["target_folder_id"])
        stored_file.folder = target
        stored_file.save(update_fields=["folder", "updated_at"])
        fallback = f"{reverse('dashboard')}?folder={stored_file.folder_id}"
        messages.success(request, "File moved.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def file_delete(request: HttpRequest, file_id: int) -> HttpResponse:
    stored_file = owned_file_or_404(request.user, file_id)
    fallback = f"{reverse('dashboard')}?folder={stored_file.folder_id}"
    stored_file.soft_delete()
    messages.success(request, "File deleted.")
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def upload_start(request: HttpRequest) -> JsonResponse:
    form = UploadStartForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    folder = owned_folder_or_404(request.user, form.cleaned_data.get("folder_id"))
    try:
        validate_upload_allowed(request.user, form.cleaned_data["size"])
    except ValidationError as exc:
        return JsonResponse({"errors": exc.messages}, status=400)
    session = UploadSession(
        owner=request.user,
        folder=folder,
        original_filename=form.cleaned_data["filename"],
        size=form.cleaned_data["size"],
        content_type=form.cleaned_data.get("content_type", ""),
        sha256_expected=form.cleaned_data.get("sha256", ""),
        expires_at=timezone.now() + timedelta(seconds=settings.PARAFILES_UPLOAD_SESSION_TTL_SECONDS),
    )
    session.temp_path = f"{session.upload_id}.part"
    session.save()
    return JsonResponse(
        {
            "upload_id": str(session.upload_id),
            "token": session.token,
            "chunk_size": 8 * 1024 * 1024,
            "bytes_received": session.bytes_received,
            "chunk_url": reverse("upload_chunk", args=[session.upload_id]),
            "status_url": reverse("upload_status", args=[session.upload_id]),
            "finalize_url": reverse("upload_finalize", args=[session.upload_id]),
        }
    )


def upload_session_or_404(request: HttpRequest, upload_id) -> UploadSession:
    token = (
        request.POST.get("token")
        or request.GET.get("token")
        or request.headers.get("x-upload-token")
    )
    return get_object_or_404(
        UploadSession,
        upload_id=upload_id,
        token=token,
        owner=request.user,
    )


@login_required
@uploader_required
def upload_status(request: HttpRequest, upload_id) -> JsonResponse:
    session = upload_session_or_404(request, upload_id)
    if session.is_expired and session.status not in {
        UploadSession.Status.FINALIZED,
        UploadSession.Status.EXPIRED,
    }:
        session.status = UploadSession.Status.EXPIRED
        session.save(update_fields=["status"])
    return JsonResponse(
        {
            "upload_id": str(session.upload_id),
            "status": session.status,
            "bytes_received": session.bytes_received,
            "size": session.size,
            "filename": session.original_filename,
            "folder_id": session.folder_id,
            "expires_at": session.expires_at.isoformat(),
            "finalized_file_id": session.finalized_file_id,
        }
    )


@login_required
@uploader_required
def upload_active(request: HttpRequest) -> JsonResponse:
    sessions = (
        UploadSession.objects.filter(
            owner=request.user,
            status__in=[UploadSession.Status.INIT, UploadSession.Status.UPLOADING],
            expires_at__gt=timezone.now(),
        )
        .select_related("folder")
        .order_by("-created_at")[:20]
    )
    return JsonResponse(
        {
            "uploads": [
                {
                    "upload_id": str(session.upload_id),
                    "token": session.token,
                    "filename": session.original_filename,
                    "size": session.size,
                    "bytes_received": session.bytes_received,
                    "status": session.status,
                    "folder_id": session.folder_id,
                    "folder_path": session.folder.logical_path(),
                    "chunk_size": 8 * 1024 * 1024,
                    "chunk_url": reverse("upload_chunk", args=[session.upload_id]),
                    "status_url": reverse("upload_status", args=[session.upload_id]),
                    "finalize_url": reverse("upload_finalize", args=[session.upload_id]),
                }
                for session in sessions
            ]
        }
    )


@require_POST
@login_required
@uploader_required
def upload_chunk(request: HttpRequest, upload_id) -> JsonResponse:
    session = upload_session_or_404(request, upload_id)
    chunk = request.FILES.get("chunk") or request.body
    offset_value = request.POST.get("offset") or request.headers.get("x-upload-offset")
    try:
        expected_offset = int(offset_value) if offset_value is not None else None
    except ValueError:
        return JsonResponse({"errors": ["Upload offset must be an integer."]}, status=400)
    try:
        write_chunk(session, chunk, expected_offset=expected_offset)
    except UploadOffsetMismatch as exc:
        return JsonResponse(
            {"errors": exc.messages, "bytes_received": session.bytes_received},
            status=409,
        )
    except ValidationError as exc:
        return JsonResponse({"errors": exc.messages}, status=400)
    return JsonResponse({"bytes_received": session.bytes_received})


def enabled_file_share_for(user: User, stored_file: StoredFile) -> PublicShare:
    share, _created = PublicShare.objects.get_or_create(
        owner=user,
        target_type=PublicShare.TargetType.FILE,
        stored_file=stored_file,
        defaults={"is_enabled": True},
    )
    if not share.is_enabled:
        share.is_enabled = True
        share.save(update_fields=["is_enabled"])
    return share


@require_POST
@login_required
@uploader_required
def upload_finalize(request: HttpRequest, upload_id) -> JsonResponse:
    session = upload_session_or_404(request, upload_id)
    try:
        stored_file = finalize_session(session)
    except ValidationError as exc:
        return JsonResponse({"errors": exc.messages}, status=400)

    if settings.PARAFILES_SCAN_SYNC:
        run_scan_for_file(stored_file.pk)
    else:
        scan_file_task.delay(stored_file.pk)
    stored_file.refresh_from_db()
    payload = {
        "file_id": stored_file.pk,
        "status": stored_file.status,
        "sha256": stored_file.sha256,
        "dashboard_url": f"{reverse('dashboard')}?folder={stored_file.folder_id}",
    }
    if request.POST.get("quick_share") == "1":
        share = enabled_file_share_for(request.user, stored_file)
        payload["share_id"] = share.pk
        payload["share_url"] = request.build_absolute_uri(reverse("public_file", args=[share.slug]))
        payload["folder_id"] = stored_file.folder_id
    return JsonResponse(payload)


@require_POST
@login_required
@uploader_required
def share_toggle(request: HttpRequest, target_type: str, target_id: int) -> HttpResponse:
    enable = request.POST.get("enabled", "1") == "1"
    if target_type == PublicShare.TargetType.FILE:
        stored_file = owned_file_or_404(request.user, target_id)
        share, _ = PublicShare.objects.get_or_create(
            owner=request.user,
            target_type=PublicShare.TargetType.FILE,
            stored_file=stored_file,
            defaults={"is_enabled": enable},
        )
        redirect_folder = stored_file.folder_id
    elif target_type == PublicShare.TargetType.FOLDER:
        folder = owned_folder_or_404(request.user, target_id)
        share, _ = PublicShare.objects.get_or_create(
            owner=request.user,
            target_type=PublicShare.TargetType.FOLDER,
            folder=folder,
            defaults={"is_enabled": enable},
        )
        redirect_folder = folder.pk
    else:
        raise Http404
    share.is_enabled = enable
    share.save(update_fields=["is_enabled"])
    messages.success(request, "Share enabled." if enable else "Share disabled.")
    fallback = f"{reverse('dashboard')}?folder={redirect_folder}"
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def share_regenerate(request: HttpRequest, share_id: int) -> HttpResponse:
    share = get_object_or_404(PublicShare, pk=share_id, owner=request.user)
    share.regenerate_slug()
    messages.success(request, "Share link regenerated.")
    if share.folder_id:
        folder_id = share.folder_id
    else:
        folder_id = share.stored_file.folder_id
    fallback = f"{reverse('dashboard')}?folder={folder_id}"
    return redirect(redirect_target(request, fallback))


@require_POST
@login_required
@uploader_required
def share_update(request: HttpRequest, share_id: int) -> HttpResponse:
    share = get_object_or_404(PublicShare, pk=share_id, owner=request.user)
    form = ShareSettingsForm(request.POST, instance=share)
    if form.is_valid():
        form.save()
        messages.success(request, "Share settings updated.")
    else:
        messages.error(request, "Share settings update failed.")
    if share.folder_id:
        folder_id = share.folder_id
    else:
        folder_id = share.stored_file.folder_id
    fallback = f"{reverse('dashboard')}?folder={folder_id}"
    return redirect(redirect_target(request, fallback))


def live_share_or_404(slug: str, target_type: str | None = None) -> PublicShare:
    queryset = PublicShare.objects.select_related("stored_file", "folder", "owner")
    share = get_object_or_404(queryset, slug=slug, is_enabled=True)
    if not share.is_live:
        raise Http404
    if target_type and share.target_type != target_type:
        raise Http404
    return share


def public_rate_limit_or_429(request: HttpRequest) -> HttpResponse | None:
    decision = check_public_page(request)
    if not decision.allowed:
        response = HttpResponse("Too many requests.", status=429)
        response["Retry-After"] = str(decision.retry_after)
        return response
    return None


def malware_scan_status_text(stored_file: StoredFile) -> str:
    if stored_file.status == StoredFile.Status.AVAILABLE:
        return "No malware detected"
    if stored_file.status == StoredFile.Status.SCANNING:
        return "Scan in progress"
    if stored_file.status == StoredFile.Status.REVIEW:
        return "Scan needs review"
    return stored_file.get_status_display()


def latest_allowed_download_at(stored_file: StoredFile):
    return (
        DownloadEvent.objects.filter(
            stored_file=stored_file,
            outcome=DownloadEvent.Outcome.ALLOWED,
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def signature_filename_for(stored_file: StoredFile) -> str:
    return f"{stored_file.original_filename}.sig"


def sibling_signature_file(
    stored_file: StoredFile, signature_file_id: int | None = None
) -> StoredFile | None:
    queryset = (
        StoredFile.objects.select_related("folder")
        .filter(
            owner_id=stored_file.owner_id,
            folder_id=stored_file.folder_id,
            original_filename=signature_filename_for(stored_file),
            status=StoredFile.Status.AVAILABLE,
            deleted_at__isnull=True,
        )
        .exclude(pk=stored_file.pk)
    )
    if signature_file_id is not None:
        queryset = queryset.filter(pk=signature_file_id)
    return queryset.order_by("pk").first()


def signature_artifact_for(
    stored_file: StoredFile, signature_file_id: int | None = None
) -> dict[str, object] | None:
    signature_file = sibling_signature_file(stored_file, signature_file_id)
    if signature_file:
        return {
            "filename": signature_file.original_filename,
            "storage_key": signature_file.storage_key,
            "size": signature_file.size,
            "signature_file_id": signature_file.pk,
        }
    if signature_file_id is not None:
        return None

    storage_key = signature_storage_key(stored_file)
    path = ensure_signature_file(stored_file)
    stat = path.stat()
    if not path.is_file():
        return None
    return {
        "filename": signature_filename_for(stored_file),
        "storage_key": storage_key,
        "size": stat.st_size,
    }


def shared_file_or_404(share: PublicShare, file_id: int | None = None) -> StoredFile:
    if file_id is None:
        if share.target_type != PublicShare.TargetType.FILE:
            raise Http404
        stored_file = share.stored_file
    else:
        stored_file = get_object_or_404(StoredFile.objects.select_related("folder"), pk=file_id)
    if (
        not stored_file
        or not stored_file.is_publicly_downloadable
        or not file_belongs_to_share(stored_file, share)
    ):
        raise Http404
    return stored_file


def public_file_context(
    *,
    share: PublicShare,
    stored_file: StoredFile,
    download_url: str,
    signature_download_url: str,
    report_url: str,
    report_form: AbuseReportForm,
    containing_folder: Folder | None = None,
) -> dict[str, object]:
    context: dict[str, object] = {
        "share": share,
        "stored_file": stored_file,
        "download_url": download_url,
        "signature_download_url": signature_download_url,
        "report_url": report_url,
        "report_form": report_form,
        "malware_scan_status": malware_scan_status_text(stored_file),
        "last_downloaded_at": latest_allowed_download_at(stored_file),
    }
    if containing_folder:
        context["containing_folder"] = containing_folder
    return context


def public_file(request: HttpRequest, slug: str) -> HttpResponse:
    limited = public_rate_limit_or_429(request)
    if limited:
        return limited
    share = live_share_or_404(slug, PublicShare.TargetType.FILE)
    stored_file = share.stored_file
    if not stored_file or not stored_file.is_publicly_downloadable:
        raise Http404
    return render(
        request,
        "fileshare/public_file.html",
        public_file_context(
            share=share,
            stored_file=stored_file,
            download_url=reverse("prepare_download", args=[share.slug]),
            signature_download_url=reverse("prepare_signature_download", args=[share.slug]),
            report_url=reverse("report_share", args=[share.slug]),
            report_form=AbuseReportForm(),
        ),
    )


def folder_tree(folder: Folder) -> list[dict]:
    output: list[dict] = []
    queue: list[tuple[Folder, int]] = [(folder, 0)]
    while queue:
        current, depth = queue.pop(0)
        files = current.files.filter(status=StoredFile.Status.AVAILABLE, deleted_at__isnull=True)
        if current.pk == folder.pk:
            relative_path = "/"
        else:
            relative_path = "/" + "/".join(current.path_parts()[len(folder.path_parts()) :])
        output.append(
            {"folder": current, "depth": depth, "relative_path": relative_path, "files": files}
        )
        children = current.children.filter(is_deleted=False).order_by("name")
        queue.extend((child, depth + 1) for child in children)
    return output


def public_folder(request: HttpRequest, slug: str) -> HttpResponse:
    limited = public_rate_limit_or_429(request)
    if limited:
        return limited
    share = live_share_or_404(slug, PublicShare.TargetType.FOLDER)
    folder = share.folder
    if not folder or not folder.is_publicly_visible:
        raise Http404
    return render(
        request,
        "fileshare/public_folder.html",
        {
            "share": share,
            "folder": folder,
            "tree": folder_tree(folder),
            "report_form": AbuseReportForm(),
        },
    )


@require_POST
def report_share(request: HttpRequest, slug: str) -> HttpResponse:
    decision = check_report(request)
    if not decision.allowed:
        response = HttpResponse("Too many reports.", status=429)
        response["Retry-After"] = str(decision.retry_after)
        return response
    share = live_share_or_404(slug)
    form = AbuseReportForm(request.POST)
    if form.is_valid():
        AbuseReport.objects.create(
            share=share,
            stored_file=share.stored_file,
            folder=share.folder,
            category=form.cleaned_data["category"],
            message=form.cleaned_data["message"],
            contact_email=form.cleaned_data.get("contact_email", ""),
            reporter_ip_hash=request_ip_hash(request),
            user_agent_hash=request_user_agent_hash(request),
        )
        return redirect("report_thanks")
    if share.target_type == PublicShare.TargetType.FILE:
        target = "fileshare/public_file.html"
    else:
        target = "fileshare/public_folder.html"
    context = {"share": share, "report_form": form}
    if share.stored_file_id:
        context = public_file_context(
            share=share,
            stored_file=share.stored_file,
            download_url=reverse("prepare_download", args=[share.slug]),
            signature_download_url=reverse("prepare_signature_download", args=[share.slug]),
            report_url=reverse("report_share", args=[share.slug]),
            report_form=form,
        )
    else:
        context["folder"] = share.folder
        context["tree"] = folder_tree(share.folder)
    return render(request, target, context, status=400)


def report_thanks(request: HttpRequest) -> HttpResponse:
    return render(request, "fileshare/report_thanks.html")


def file_belongs_to_share(stored_file: StoredFile, share: PublicShare) -> bool:
    if share.target_type == PublicShare.TargetType.FILE:
        return share.stored_file_id == stored_file.pk
    if share.folder_id:
        return share.folder.contains(stored_file.folder)
    return False


def selected_file_id(request: HttpRequest, file_id: int | None = None) -> int | None:
    if file_id is not None:
        return file_id
    posted_file_id = request.POST.get("file_id")
    if not posted_file_id:
        return None
    try:
        return int(posted_file_id)
    except ValueError:
        raise Http404 from None


@require_POST
def prepare_download(request: HttpRequest, slug: str, file_id: int | None = None) -> HttpResponse:
    share = live_share_or_404(slug)
    file_id = selected_file_id(request, file_id)
    stored_file = shared_file_or_404(share, file_id)

    decision = check_download_request(request, stored_file.size)
    if not decision.allowed:
        DownloadEvent.objects.create(
            stored_file=stored_file,
            share=share,
            ip_hash=request_ip_hash(request),
            user_agent_hash=request_user_agent_hash(request),
            outcome=DownloadEvent.Outcome.RATE_LIMITED,
        )
        response = HttpResponse("Too many downloads.", status=429)
        response["Retry-After"] = str(decision.retry_after)
        return response

    token = create_download_token(
        stored_file,
        share,
        request_ip_hash(request),
        request_user_agent_hash(request),
        concurrency_key=decision.concurrency_key,
        slowed=decision.slowed,
        limit_rate=decision.limit_rate,
    )
    url = reverse("download_file", args=[token])
    response = redirect(url)
    if decision.slowed:
        response["X-Parafiles-Slowed"] = "1"
    return response


@require_POST
def prepare_signature_download(
    request: HttpRequest, slug: str, file_id: int | None = None
) -> HttpResponse:
    share = live_share_or_404(slug)
    file_id = selected_file_id(request, file_id)
    stored_file = shared_file_or_404(share, file_id)
    signature_artifact = signature_artifact_for(stored_file)
    if not signature_artifact:
        raise Http404

    decision = check_download_request(request, int(signature_artifact["size"]))
    if not decision.allowed:
        DownloadEvent.objects.create(
            stored_file=stored_file,
            share=share,
            ip_hash=request_ip_hash(request),
            user_agent_hash=request_user_agent_hash(request),
            outcome=DownloadEvent.Outcome.RATE_LIMITED,
        )
        response = HttpResponse("Too many downloads.", status=429)
        response["Retry-After"] = str(decision.retry_after)
        return response

    token = create_download_token(
        stored_file,
        share,
        request_ip_hash(request),
        request_user_agent_hash(request),
        concurrency_key=decision.concurrency_key,
        slowed=decision.slowed,
        limit_rate=decision.limit_rate,
        asset="signature",
        signature_file_id=signature_artifact.get("signature_file_id"),
    )
    url = reverse("download_file", args=[token])
    response = redirect(url)
    if decision.slowed:
        response["X-Parafiles-Slowed"] = "1"
    return response


def token_cache_key(token: str) -> str:
    return "download-token-used:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def private_download_response(
    *,
    storage_key: str,
    filename: str,
    size: int,
    content_type: str,
    limit_rate: int | None = None,
) -> HttpResponse:
    disposition = content_disposition(filename)
    if settings.PARAFILES_SERVE_PRIVATE_DOWNLOADS:
        response = FileResponse(
            private_path(storage_key).open("rb"),
            as_attachment=True,
            filename=filename,
        )
    else:
        response = HttpResponse()
        response["X-Accel-Redirect"] = settings.PARAFILES_INTERNAL_DOWNLOAD_PREFIX + quote(
            storage_key
        )
    response["Content-Type"] = content_type
    response["Content-Length"] = str(size)
    response["Content-Disposition"] = disposition
    response["X-Content-Type-Options"] = "nosniff"
    if limit_rate:
        response["X-Accel-Limit-Rate"] = str(limit_rate)
    return response


def download_signature_file(
    stored_file: StoredFile, share: PublicShare, token_payload: dict
) -> HttpResponse:
    if not stored_file.is_publicly_downloadable or not file_belongs_to_share(stored_file, share):
        release_download_slot(token_payload.get("ck", ""))
        raise Http404

    signature_file_id = token_payload.get("signature_file_id")
    signature_artifact = signature_artifact_for(
        stored_file, signature_file_id if isinstance(signature_file_id, int) else None
    )
    if not signature_artifact:
        release_download_slot(token_payload.get("ck", ""))
        raise Http404

    response = private_download_response(
        storage_key=str(signature_artifact["storage_key"]),
        filename=str(signature_artifact["filename"]),
        size=int(signature_artifact["size"]),
        content_type="application/json",
        limit_rate=token_payload["rate"]
        if token_payload.get("slow") and token_payload.get("rate")
        else None,
    )
    release_download_slot(token_payload.get("ck", ""))
    return response


def download_file(request: HttpRequest, token: str) -> HttpResponse:
    from django.core.cache import cache

    cache_key = token_cache_key(token)
    if not cache.add(cache_key, "1", settings.PARAFILES_DOWNLOAD_TOKEN_TTL_SECONDS):
        raise PermissionDenied("Download token already used.")

    try:
        stored_file, share, token_payload = load_download_token(
            token, request_ip_hash(request), request_user_agent_hash(request)
        )
    except (PermissionDenied, SuspiciousOperation):
        raise
    asset = token_payload.get("asset", "file")
    if asset == "signature":
        return download_signature_file(stored_file, share, token_payload)
    if asset != "file":
        release_download_slot(token_payload.get("ck", ""))
        raise SuspiciousOperation("Invalid download asset.")
    if not stored_file.is_publicly_downloadable or not file_belongs_to_share(stored_file, share):
        release_download_slot(token_payload.get("ck", ""))
        DownloadEvent.objects.create(
            stored_file=stored_file,
            share=share,
            ip_hash=request_ip_hash(request),
            user_agent_hash=request_user_agent_hash(request),
            outcome=DownloadEvent.Outcome.DENIED,
        )
        raise Http404

    DownloadEvent.objects.create(
        stored_file=stored_file,
        share=share,
        ip_hash=request_ip_hash(request),
        user_agent_hash=request_user_agent_hash(request),
        bytes_served=stored_file.size,
        outcome=DownloadEvent.Outcome.ALLOWED,
    )
    StoredFile.objects.filter(pk=stored_file.pk).update(download_count=F("download_count") + 1)

    response = private_download_response(
        storage_key=stored_file.storage_key,
        filename=stored_file.original_filename,
        size=stored_file.size,
        content_type="application/octet-stream",
        limit_rate=token_payload["rate"]
        if token_payload.get("slow") and token_payload.get("rate")
        else None,
    )
    release_download_slot(token_payload.get("ck", ""))
    return response


@staff_member_required
def moderation_dashboard(request: HttpRequest) -> HttpResponse:
    filter_form = ModerationFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
    report_status = filters.get("report_status", "")
    file_status = filters.get("file_status", "")
    assigned_to = filters.get("assigned_to")

    reports_queryset = AbuseReport.objects.select_related(
        "share", "stored_file", "folder", "assigned_to", "handled_by"
    )
    files_queryset = StoredFile.objects.select_related("owner", "folder")
    folders_queryset = Folder.objects.select_related("owner", "parent")

    if q:
        reports_queryset = reports_queryset.filter(
            Q(message__icontains=q)
            | Q(contact_email__icontains=q)
            | Q(stored_file__original_filename__icontains=q)
            | Q(stored_file__title__icontains=q)
            | Q(stored_file__sha256__icontains=q)
            | Q(folder__name__icontains=q)
            | Q(share__slug__icontains=q)
        )
        files_queryset = files_queryset.filter(
            Q(original_filename__icontains=q)
            | Q(title__icontains=q)
            | Q(sha256__icontains=q)
            | Q(owner__username__icontains=q)
            | Q(owner__email__icontains=q)
        )
        folders_queryset = folders_queryset.filter(
            Q(name__icontains=q) | Q(owner__username__icontains=q) | Q(owner__email__icontains=q)
        )
    if report_status:
        reports_queryset = reports_queryset.filter(status=report_status)
    if file_status:
        files_queryset = files_queryset.filter(status=file_status)
    if assigned_to:
        reports_queryset = reports_queryset.filter(assigned_to=assigned_to)

    reports = list(reports_queryset.order_by("-created_at")[:100])
    recent_files = list(files_queryset.order_by("-uploaded_at")[:100])
    recent_folders = list(folders_queryset.order_by("-updated_at")[:100])
    for report in reports:
        report.moderation_form = ReportModerationForm(instance=report)
        report.duplicate_count = duplicate_report_count(report)
    summary = {
        "open_reports": AbuseReport.objects.filter(status=AbuseReport.Status.OPEN).count(),
        "reviewing_reports": AbuseReport.objects.filter(
            status=AbuseReport.Status.REVIEWING
        ).count(),
        "review_files": StoredFile.objects.filter(status=StoredFile.Status.REVIEW).count(),
        "quarantined_files": StoredFile.objects.filter(
            status=StoredFile.Status.QUARANTINED
        ).count(),
        "recent_blocks": RateLimitEvent.objects.filter(action=RateLimitEvent.Action.BLOCK).count(),
    }
    return render(
        request,
        "fileshare/moderation_dashboard.html",
        {
            "filter_form": filter_form,
            "summary": summary,
            "reports": reports,
            "recent_files": recent_files,
            "recent_folders": recent_folders,
        },
    )


@staff_member_required
def moderation_action_log(request: HttpRequest) -> HttpResponse:
    filter_form = ModerationActionFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
    action = filters.get("action", "")
    actor = filters.get("actor")

    actions_queryset = ModerationAction.objects.select_related(
        "actor", "stored_file", "folder", "share", "report", "target_user"
    )
    if q:
        actions_queryset = actions_queryset.filter(
            Q(reason__icontains=q)
            | Q(actor__username__icontains=q)
            | Q(actor__email__icontains=q)
            | Q(stored_file__original_filename__icontains=q)
            | Q(stored_file__title__icontains=q)
            | Q(stored_file__sha256__icontains=q)
            | Q(folder__name__icontains=q)
            | Q(share__slug__icontains=q)
            | Q(report__message__icontains=q)
            | Q(target_user__username__icontains=q)
            | Q(target_user__email__icontains=q)
        )
    if action:
        actions_queryset = actions_queryset.filter(action=action)
    if actor:
        actions_queryset = actions_queryset.filter(actor=actor)

    actions = list(actions_queryset.order_by("-created_at")[:200])
    return render(
        request,
        "fileshare/moderation_action_log.html",
        {
            "filter_form": filter_form,
            "actions": actions,
        },
    )


@staff_member_required
def moderation_rate_limit_events(request: HttpRequest) -> HttpResponse:
    filter_form = RateLimitEventFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
    scope = filters.get("scope", "")
    action = filters.get("action", "")

    events_queryset = RateLimitEvent.objects.all()
    if q:
        events_queryset = events_queryset.filter(
            Q(scope__icontains=q)
            | Q(key__icontains=q)
            | Q(ip_hash__icontains=q)
            | Q(user_agent_hash__icontains=q)
        )
    if scope:
        events_queryset = events_queryset.filter(scope__icontains=scope)
    if action:
        events_queryset = events_queryset.filter(action=action)

    events = list(events_queryset.order_by("-created_at")[:200])
    summary = {
        "warn": RateLimitEvent.objects.filter(action=RateLimitEvent.Action.WARN).count(),
        "slow": RateLimitEvent.objects.filter(action=RateLimitEvent.Action.SLOW).count(),
        "block": RateLimitEvent.objects.filter(action=RateLimitEvent.Action.BLOCK).count(),
    }
    return render(
        request,
        "fileshare/moderation_rate_limit_events.html",
        {
            "filter_form": filter_form,
            "events": events,
            "summary": summary,
        },
    )


def email_diagnostic_settings() -> list[dict[str, str]]:
    password_state = "Set (hidden)" if settings.EMAIL_HOST_PASSWORD else "Not set"
    host_user = settings.EMAIL_HOST_USER or "Not set"
    return [
        {"name": "Email backend", "value": settings.EMAIL_BACKEND},
        {"name": "Default from", "value": settings.DEFAULT_FROM_EMAIL or "Not set"},
        {"name": "SMTP host", "value": settings.EMAIL_HOST or "Not set"},
        {"name": "SMTP port", "value": str(settings.EMAIL_PORT)},
        {"name": "SMTP username", "value": host_user},
        {"name": "SMTP password", "value": password_state},
        {"name": "Use TLS", "value": "Yes" if settings.EMAIL_USE_TLS else "No"},
        {"name": "Use SSL", "value": "Yes" if settings.EMAIL_USE_SSL else "No"},
        {"name": "Timeout", "value": f"{settings.EMAIL_TIMEOUT} seconds"},
    ]


def email_configuration_notes() -> list[dict[str, str]]:
    notes = []
    backend = settings.EMAIL_BACKEND
    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        notes.append(
            {
                "status": "error",
                "detail": "EMAIL_USE_TLS and EMAIL_USE_SSL are both enabled. Use only one.",
            }
        )
    if backend.endswith("console.EmailBackend"):
        notes.append(
            {
                "status": "warn",
                "detail": "The console email backend writes messages to server output and does not contact SMTP.",
            }
        )
    if backend.endswith("locmem.EmailBackend"):
        notes.append(
            {
                "status": "warn",
                "detail": "The in-memory email backend captures messages for tests and does not contact SMTP.",
            }
        )
    if backend.endswith("smtp.EmailBackend") and not settings.EMAIL_HOST_USER:
        notes.append(
            {
                "status": "warn",
                "detail": "SMTP username is empty. Authenticated providers usually require EMAIL_HOST_USER.",
            }
        )
    return notes


def exception_detail(exc: Exception) -> str:
    detail = f"{exc.__class__.__name__}: {exc}"
    smtp_code = getattr(exc, "smtp_code", None)
    smtp_error = getattr(exc, "smtp_error", None)
    if isinstance(smtp_error, bytes):
        smtp_error = smtp_error.decode("utf-8", errors="replace")
    if smtp_code is not None and smtp_error:
        detail = f"{detail} (SMTP {smtp_code}: {smtp_error})"
    return detail


def run_email_diagnostic(recipient: str, subject: str, body: str) -> dict:
    started_at = timezone.now()
    started = time.monotonic()
    steps: list[dict[str, str | int]] = []
    status = "ok"
    connection_obj = None
    backend_class = settings.EMAIL_BACKEND

    def add_step(name: str, step_status: str, detail: str, step_started: float) -> None:
        steps.append(
            {
                "name": name,
                "status": step_status,
                "detail": detail,
                "duration_ms": round((time.monotonic() - step_started) * 1000),
            }
        )

    def finish() -> dict:
        return {
            "status": status,
            "started_at": started_at,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "backend": backend_class,
            "sender": settings.DEFAULT_FROM_EMAIL,
            "recipient": recipient,
            "steps": steps,
        }

    step_started = time.monotonic()
    try:
        connection_obj = get_connection(fail_silently=False)
        backend_class = (
            f"{connection_obj.__class__.__module__}.{connection_obj.__class__.__name__}"
        )
    except Exception as exc:
        status = "error"
        add_step("Build backend", "error", exception_detail(exc), step_started)
        return finish()
    add_step("Build backend", "ok", backend_class, step_started)

    step_started = time.monotonic()
    try:
        opened = connection_obj.open()
    except Exception as exc:
        status = "error"
        add_step("Open connection", "error", exception_detail(exc), step_started)
        try:
            connection_obj.close()
        except Exception:
            pass
        return finish()
    if opened:
        open_detail = "Connection opened and backend authentication completed."
    else:
        open_detail = "Backend did not need a new network connection."
    add_step("Open connection", "ok", open_detail, step_started)

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        headers={"X-Parafiles-Diagnostic": "true"},
        connection=connection_obj,
    )
    step_started = time.monotonic()
    try:
        sent_count = connection_obj.send_messages([message]) or 0
    except Exception as exc:
        status = "error"
        add_step("Send message", "error", exception_detail(exc), step_started)
    else:
        if sent_count == 1:
            add_step("Send message", "ok", "Backend accepted 1 message.", step_started)
        else:
            status = "warn"
            add_step(
                "Send message",
                "warn",
                f"Backend returned {sent_count} accepted messages.",
                step_started,
            )

    step_started = time.monotonic()
    try:
        connection_obj.close()
    except Exception as exc:
        if status == "ok":
            status = "warn"
        add_step("Close connection", "warn", exception_detail(exc), step_started)
    else:
        add_step("Close connection", "ok", "Connection closed.", step_started)
    return finish()


@staff_member_required
def moderation_operations_health(request: HttpRequest) -> HttpResponse:
    status, checks = operations_health()
    return render(
        request,
        "fileshare/moderation_operations_health.html",
        {
            "status": status,
            "checks": checks,
        },
    )


@staff_member_required
def moderation_email_diagnostics(request: HttpRequest) -> HttpResponse:
    result = None
    if request.method == "POST":
        form = EmailDiagnosticForm(request.POST)
        if form.is_valid():
            result = run_email_diagnostic(
                form.cleaned_data["recipient"],
                form.cleaned_data["subject"],
                form.cleaned_data["body"],
            )
            if result["status"] == "ok":
                messages.success(request, "Diagnostic email accepted by the configured backend.")
            elif result["status"] == "warn":
                messages.warning(request, "Diagnostic email completed with warnings.")
            else:
                messages.error(request, "Diagnostic email did not complete successfully.")
    else:
        form = EmailDiagnosticForm(initial={"recipient": request.user.email})

    return render(
        request,
        "fileshare/moderation_email_diagnostics.html",
        {
            "form": form,
            "email_settings": email_diagnostic_settings(),
            "configuration_notes": email_configuration_notes(),
            "result": result,
        },
    )


@staff_member_required
def moderation_users(request: HttpRequest) -> HttpResponse:
    filter_form = UserModerationFilterForm(request.GET)
    filters = filter_form.cleaned_data if filter_form.is_valid() else {}
    q = filters.get("q", "")
    state = filters.get("state", "")

    users_queryset = User.objects.annotate(
        upload_count=Count("files", filter=~Q(files__status=StoredFile.Status.DELETED)),
        active_share_count=Count("public_shares", filter=Q(public_shares__is_enabled=True)),
        storage_bytes=Sum("files__size", filter=~Q(files__status=StoredFile.Status.DELETED)),
    )
    if q:
        users_queryset = users_queryset.filter(Q(username__icontains=q) | Q(email__icontains=q))
    if state == "active":
        users_queryset = users_queryset.filter(is_active=True)
    elif state == "inactive":
        users_queryset = users_queryset.filter(is_active=False)
    elif state == "uploader":
        users_queryset = users_queryset.filter(is_uploader=True)
    elif state == "not_uploader":
        users_queryset = users_queryset.filter(is_uploader=False)
    elif state == "staff":
        users_queryset = users_queryset.filter(is_staff=True)

    users = list(users_queryset.order_by("username")[:200])
    return render(
        request,
        "fileshare/moderation_users.html",
        {
            "filter_form": filter_form,
            "users": users,
        },
    )


def share_public_url(request: HttpRequest, share: PublicShare) -> str:
    if share.target_type == PublicShare.TargetType.FILE:
        path = reverse("public_file", args=[share.slug])
    else:
        path = reverse("public_folder", args=[share.slug])
    return request.build_absolute_uri(path)


@staff_member_required
def moderation_user_files(request: HttpRequest, user_id: int) -> HttpResponse:
    target_user = get_object_or_404(User, pk=user_id)
    folders = list(
        Folder.objects.filter(owner=target_user)
        .select_related("parent")
        .prefetch_related("public_shares")
        .annotate(
            direct_file_count=Count("files", filter=~Q(files__status=StoredFile.Status.DELETED)),
            direct_download_count=Sum(
                "files__download_count", filter=~Q(files__status=StoredFile.Status.DELETED)
            ),
        )
        .order_by("parent_id", "name", "id")
    )
    files = list(
        StoredFile.objects.filter(owner=target_user)
        .exclude(status=StoredFile.Status.DELETED)
        .select_related("folder")
        .prefetch_related("public_shares")
        .annotate(
            allowed_download_events=Count(
                "download_events",
                filter=Q(download_events__outcome=DownloadEvent.Outcome.ALLOWED),
            )
        )
        .order_by("folder__name", "original_filename")
    )
    for folder in folders:
        folder.active_links = [
            share_public_url(request, share)
            for share in folder.public_shares.all()
            if share.is_live
        ]
    for stored_file in files:
        direct_links = [
            share_public_url(request, share)
            for share in stored_file.public_shares.all()
            if share.is_live
        ]
        stored_file.active_links = direct_links

    context = {
        "account": target_user,
        "folders": folders,
        "files": files,
        "used_bytes": storage_used(target_user),
        "file_count": file_count(target_user),
        "folder_count": Folder.objects.filter(owner=target_user, is_deleted=False).count(),
        "download_count": DownloadEvent.objects.filter(
            stored_file__owner=target_user,
            outcome=DownloadEvent.Outcome.ALLOWED,
        ).count(),
    }
    return render(request, "fileshare/moderation_user_files.html", context)


@staff_member_required
def moderation_invitations(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = InvitationCreateForm(request.POST)
        if form.is_valid():
            invitation = Invitation.objects.create(
                email=form.cleaned_data["email"],
                created_by=request.user,
                expires_at=timezone.now() + timedelta(days=form.cleaned_data["expires_in_days"]),
            )
            if form.cleaned_data["send_email"]:
                send_invitation_email(invitation, invitation_url(request, invitation))
                messages.success(request, "Invitation created and emailed.")
            else:
                messages.success(request, "Invitation created.")
            return redirect("moderation_invitations")
        messages.error(request, "Invitation could not be created.")
    else:
        form = InvitationCreateForm()

    invitations = Invitation.objects.select_related("created_by", "accepted_by").order_by(
        "-created_at"
    )[:100]
    return render(
        request,
        "fileshare/moderation_invitations.html",
        {
            "form": form,
            "invitations": invitations,
        },
    )


@require_POST
@staff_member_required
def moderation_invitation_resend(request: HttpRequest, invitation_id: int) -> HttpResponse:
    invitation = get_object_or_404(Invitation, pk=invitation_id)
    if not invitation.is_usable:
        messages.error(request, "Only unused, unexpired invitations can be resent.")
    elif not invitation.email:
        messages.error(request, "This invitation has no email address.")
    else:
        send_invitation_email(invitation, invitation_url(request, invitation))
        messages.success(request, "Invitation email resent.")
    return redirect(redirect_target(request, reverse("moderation_invitations")))


def apply_user_moderation(target_user: User, action: str, actor, reason: str = "") -> None:
    metadata = {}
    if action == ModerationAction.Action.SUSPEND_USER:
        target_user.is_active = False
        target_user.is_uploader = False
        target_user.save(update_fields=["is_active", "is_uploader"])
        disabled = PublicShare.objects.filter(owner=target_user, is_enabled=True).update(
            is_enabled=False
        )
        metadata["disabled_shares"] = disabled
    elif action == ModerationAction.Action.DISABLE_UPLOADS:
        target_user.is_uploader = False
        target_user.save(update_fields=["is_uploader"])
    elif action == ModerationAction.Action.DISABLE_USER_SHARES:
        disabled = PublicShare.objects.filter(owner=target_user, is_enabled=True).update(
            is_enabled=False
        )
        metadata["disabled_shares"] = disabled
    elif action == ModerationAction.Action.RESTORE_USER:
        target_user.is_active = True
        target_user.is_uploader = True
        target_user.save(update_fields=["is_active", "is_uploader"])
    else:
        raise Http404
    record_action(actor, action, target_user=target_user, reason=reason, metadata=metadata)


@require_POST
@staff_member_required
def moderate_user(request: HttpRequest, user_id: int, action: str) -> HttpResponse:
    target_user = get_object_or_404(User, pk=user_id)
    if target_user == request.user and action == ModerationAction.Action.SUSPEND_USER:
        raise PermissionDenied("Staff cannot suspend their own account.")
    reason = request.POST.get("reason", "")
    apply_user_moderation(target_user, action, request.user, reason)
    messages.success(request, "User moderation action applied.")
    return redirect(redirect_target(request, reverse("moderation_users")))


@staff_member_required
def moderation_user_quota(request: HttpRequest, user_id: int) -> HttpResponse:
    target_user = get_object_or_404(User, pk=user_id)
    quota_override = getattr(target_user, "quota_override", None)
    if request.method == "POST":
        form = QuotaOverrideForm(request.POST, quota_override=quota_override)
        if form.is_valid():
            values = form.quota_values()
            if all(value is None for value in values.values()):
                if quota_override:
                    quota_override.delete()
                metadata = {"cleared": True}
            else:
                quota_override, _created = QuotaOverride.objects.update_or_create(
                    user=target_user,
                    defaults=values,
                )
                metadata = values
            record_action(
                request.user,
                ModerationAction.Action.UPDATE_QUOTA,
                target_user=target_user,
                metadata=metadata,
            )
            messages.success(request, "Quota override updated.")
            return redirect("moderation_user_quota", user_id=target_user.pk)
        messages.error(request, "Quota override update failed.")
    else:
        form = QuotaOverrideForm(quota_override=quota_override)

    context = {
        "account": target_user,
        "form": form,
        "quota": effective_quota(target_user),
        "quota_override": quota_override,
        "used_bytes": storage_used(target_user),
        "file_count": file_count(target_user),
        "folder_count": Folder.objects.filter(owner=target_user, is_deleted=False).count(),
    }
    return render(request, "fileshare/moderation_user_quota.html", context)


def duplicate_report_count(report: AbuseReport) -> int:
    queryset = AbuseReport.objects.exclude(pk=report.pk)
    if report.stored_file_id:
        return queryset.filter(stored_file_id=report.stored_file_id).count()
    if report.folder_id:
        return queryset.filter(folder_id=report.folder_id).count()
    if report.share_id:
        return queryset.filter(share_id=report.share_id).count()
    return 0


def apply_file_moderation(stored_file: StoredFile, action: str, actor, reason: str = "") -> None:
    if action == ModerationAction.Action.HIDE:
        stored_file.hide()
    elif action == ModerationAction.Action.QUARANTINE:
        stored_file.quarantine()
    elif action == ModerationAction.Action.RESTORE:
        stored_file.restore()
    elif action == ModerationAction.Action.DELETE:
        stored_file.soft_delete()
    elif action == ModerationAction.Action.PURGE:
        purge_file_bytes(stored_file)
    elif action == ModerationAction.Action.RESCAN:
        if settings.PARAFILES_SCAN_SYNC:
            run_scan_for_file(stored_file.pk)
        else:
            scan_file_task.delay(stored_file.pk)
    else:
        raise Http404
    record_action(actor, action, stored_file=stored_file, reason=reason)


def apply_folder_moderation(folder: Folder, action: str, actor, reason: str = "") -> None:
    if folder.is_root:
        raise PermissionDenied("The root folder cannot be moderated directly.")
    if action in {ModerationAction.Action.HIDE, ModerationAction.Action.DELETE}:
        folder.soft_delete()
    elif action == ModerationAction.Action.RESTORE:
        folder.restore()
    elif action == ModerationAction.Action.PURGE:
        purge_folder_tree(folder)
    else:
        raise Http404
    record_action(actor, action, folder=folder, reason=reason)


def apply_share_moderation(share: PublicShare, action: str, actor, reason: str = "") -> None:
    metadata = {}
    recorded_action = action
    if action in {ModerationAction.Action.HIDE, "disable"}:
        share.is_enabled = False
        share.save(update_fields=["is_enabled"])
        recorded_action = ModerationAction.Action.HIDE
    elif action in {ModerationAction.Action.RESTORE, "enable"}:
        share.is_enabled = True
        share.save(update_fields=["is_enabled"])
        recorded_action = ModerationAction.Action.RESTORE
    elif action == ModerationAction.Action.REGENERATE_SHARE:
        old_slug = share.slug
        share.regenerate_slug()
        metadata = {"old_slug": old_slug, "new_slug": share.slug}
    else:
        raise Http404
    record_action(actor, recorded_action, share=share, reason=reason, metadata=metadata)


def update_report_status(report: AbuseReport, status: str, actor, reason: str = "") -> None:
    if status not in AbuseReport.Status.values:
        raise Http404
    report.status = status
    if status in {AbuseReport.Status.RESOLVED, AbuseReport.Status.REJECTED}:
        report.resolved_at = timezone.now()
        report.handled_by = actor
    else:
        report.resolved_at = None
        report.handled_by = None
    report.save(update_fields=["status", "resolved_at", "handled_by", "updated_at"])
    record_action(
        actor,
        ModerationAction.Action.RESOLVE_REPORT,
        report=report,
        reason=reason,
        metadata={"status": status},
    )


@require_POST
@staff_member_required
def moderate_file(request: HttpRequest, file_id: int, action: str) -> HttpResponse:
    stored_file = get_object_or_404(StoredFile, pk=file_id)
    reason = request.POST.get("reason", "")
    apply_file_moderation(stored_file, action, request.user, reason)
    messages.success(request, "Moderation action applied.")
    return redirect(redirect_target(request, reverse("moderation_dashboard")))


@require_POST
@staff_member_required
def moderate_folder(request: HttpRequest, folder_id: int, action: str) -> HttpResponse:
    folder = get_object_or_404(Folder, pk=folder_id)
    reason = request.POST.get("reason", "")
    apply_folder_moderation(folder, action, request.user, reason)
    messages.success(request, "Folder moderation action applied.")
    return redirect(redirect_target(request, reverse("moderation_dashboard")))


@require_POST
@staff_member_required
def moderate_share(request: HttpRequest, share_id: int, action: str) -> HttpResponse:
    share = get_object_or_404(PublicShare, pk=share_id)
    reason = request.POST.get("reason", "")
    apply_share_moderation(share, action, request.user, reason)
    messages.success(request, "Share moderation action applied.")
    return redirect(redirect_target(request, reverse("moderation_dashboard")))


@require_POST
@staff_member_required
def moderate_report(request: HttpRequest, report_id: int, status: str) -> HttpResponse:
    report = get_object_or_404(AbuseReport, pk=report_id)
    update_report_status(report, status, request.user)
    return redirect(redirect_target(request, reverse("moderation_dashboard")))


@require_POST
@staff_member_required
def moderate_report_update(request: HttpRequest, report_id: int) -> HttpResponse:
    report = get_object_or_404(AbuseReport, pk=report_id)
    form = ReportModerationForm(request.POST, instance=report)
    if form.is_valid():
        updated_report = form.save(commit=False)
        if updated_report.status in {AbuseReport.Status.RESOLVED, AbuseReport.Status.REJECTED}:
            if not updated_report.resolved_at:
                updated_report.resolved_at = timezone.now()
            updated_report.handled_by = request.user
        else:
            updated_report.resolved_at = None
            updated_report.handled_by = None
        updated_report.save()
        record_action(
            request.user,
            ModerationAction.Action.RESOLVE_REPORT,
            report=updated_report,
            metadata={
                "status": updated_report.status,
                "assigned_to": updated_report.assigned_to_id,
            },
        )
        messages.success(request, "Report updated.")
    else:
        messages.error(request, "Report update failed.")
    return redirect(redirect_target(request, reverse("moderation_dashboard")))


@staff_member_required
def moderation_report_detail(request: HttpRequest, report_id: int) -> HttpResponse:
    report = get_object_or_404(
        AbuseReport.objects.select_related(
            "share", "stored_file", "folder", "assigned_to", "handled_by"
        ),
        pk=report_id,
    )
    related_reports = related_reports_for(report)
    action_filter = Q(report=report)
    if report.stored_file_id:
        action_filter |= Q(stored_file=report.stored_file)
    if report.folder_id:
        action_filter |= Q(folder=report.folder)
    if report.share_id:
        action_filter |= Q(share=report.share)
    actions = ModerationAction.objects.filter(action_filter).select_related("actor")[:50]
    return render(
        request,
        "fileshare/moderation_report_detail.html",
        {
            "report": report,
            "form": ReportModerationForm(instance=report),
            "related_reports": related_reports,
            "actions": actions,
        },
    )


def related_reports_for(report: AbuseReport):
    queryset = AbuseReport.objects.exclude(pk=report.pk).select_related(
        "stored_file", "folder", "share", "assigned_to"
    )
    if report.stored_file_id:
        return queryset.filter(stored_file_id=report.stored_file_id).order_by("-created_at")[:25]
    if report.folder_id:
        return queryset.filter(folder_id=report.folder_id).order_by("-created_at")[:25]
    if report.share_id:
        return queryset.filter(share_id=report.share_id).order_by("-created_at")[:25]
    return AbuseReport.objects.none()


@require_POST
@staff_member_required
def moderation_bulk_action(request: HttpRequest) -> HttpResponse:
    data = request.POST.copy()
    if request.POST.getlist("ids"):
        data["ids"] = ",".join(request.POST.getlist("ids"))
    form = ModerationBulkActionForm(data)
    if not form.is_valid():
        messages.error(request, "Bulk action failed.")
        return redirect("moderation_dashboard")

    target = form.cleaned_data["target"]
    action = form.cleaned_data["action"]
    ids = form.cleaned_data["ids"]
    reason = form.cleaned_data["reason"]
    count = 0
    if target == "reports":
        for report in AbuseReport.objects.filter(pk__in=ids):
            update_report_status(report, action, request.user, reason)
            count += 1
    elif target == "files":
        for stored_file in StoredFile.objects.filter(pk__in=ids):
            apply_file_moderation(stored_file, action, request.user, reason)
            count += 1
    elif target == "folders":
        for folder in Folder.objects.filter(pk__in=ids):
            if folder.is_root:
                continue
            apply_folder_moderation(folder, action, request.user, reason)
            count += 1
    else:
        raise Http404
    messages.success(request, f"Bulk action applied to {count} item(s).")
    return redirect(redirect_target(request, reverse("moderation_dashboard")))


def health_check(request: HttpRequest) -> JsonResponse:
    checks: dict[str, str] = {}
    status_code = 200
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
        status_code = 503

    try:
        cache_key = "health-check"
        cache.set(cache_key, "ok", 5)
        checks["cache"] = "ok" if cache.get(cache_key) == "ok" else "error: mismatch"
        if checks["cache"] != "ok":
            status_code = 503
    except Exception as exc:
        checks["cache"] = f"error: {exc.__class__.__name__}"
        status_code = 503

    return JsonResponse(
        {"status": "ok" if status_code == 200 else "degraded", "checks": checks},
        status=status_code,
    )


def permission_denied(request: HttpRequest, exception=None) -> HttpResponse:
    return render(request, "403.html", status=403)


def page_not_found(request: HttpRequest, exception=None) -> HttpResponse:
    return render(request, "404.html", status=404)
