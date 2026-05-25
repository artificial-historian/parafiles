from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse
from django.utils import timezone

from .models import (
    AbuseReport,
    DownloadEvent,
    Folder,
    Invitation,
    ModerationAction,
    PublicShare,
    QuotaOverride,
    RateLimitEvent,
    ScanResult,
    StoredFile,
    UploadSession,
    User,
)
from .services.moderation import record_action
from .services.invitations import send_invitation_email
from .services.scanning import run_scan_for_file
from .tasks import scan_file_task


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "verified_email",
        "is_uploader",
        "is_staff",
        "is_active",
        "date_joined",
    )
    list_filter = ("is_uploader", "is_staff", "is_active")
    search_fields = ("username", "email")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Parafiles",
            {
                "fields": (
                    "verified_email",
                    "email_verified_at",
                    "pending_email",
                    "is_uploader",
                    "storage_quota_bytes",
                    "max_file_size_bytes",
                    "max_file_count",
                    "folder_depth_limit",
                )
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Parafiles",
            {
                "fields": (
                    "is_uploader",
                    "storage_quota_bytes",
                    "max_file_size_bytes",
                    "max_file_count",
                    "folder_depth_limit",
                )
            },
        ),
    )


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "token", "created_by", "created_at", "expires_at", "accepted_at")
    list_filter = ("accepted_at", "expires_at")
    search_fields = ("email", "token")
    readonly_fields = ("token", "created_at", "accepted_at", "accepted_by")
    actions = ("resend_invitation_email",)

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        if not change and obj.email and obj.is_usable:
            url = request.build_absolute_uri(reverse("register_invite", args=[obj.token]))
            send_invitation_email(obj, url)
            self.message_user(request, "Invitation email sent.", messages.SUCCESS)

    @admin.action(description="Resend selected invitation emails")
    def resend_invitation_email(self, request, queryset):
        sent = 0
        for invitation in queryset:
            if invitation.email and invitation.is_usable:
                url = request.build_absolute_uri(reverse("register_invite", args=[invitation.token]))
                sent += send_invitation_email(invitation, url)
        self.message_user(request, f"Resent {sent} invitation email(s).", messages.SUCCESS)


class ScanResultInline(admin.TabularInline):
    model = ScanResult
    extra = 0
    readonly_fields = ("engine", "status", "signature", "raw_result", "created_at")
    can_delete = False


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "owner", "size", "status", "sha256", "uploaded_at")
    list_filter = ("status", "uploaded_at")
    search_fields = ("original_filename", "sha256", "owner__username", "owner__email")
    readonly_fields = ("storage_key", "sha256", "uploaded_at", "updated_at", "download_count")
    actions = (
        "hide_files",
        "quarantine_files",
        "restore_files",
        "soft_delete_files",
        "rescan_files",
    )
    inlines = [ScanResultInline]

    @admin.action(description="Hide selected files")
    def hide_files(self, request, queryset):
        for stored_file in queryset:
            stored_file.hide()
            record_action(request.user, ModerationAction.Action.HIDE, stored_file=stored_file)
        self.message_user(request, "Selected files hidden.", messages.SUCCESS)

    @admin.action(description="Quarantine selected files")
    def quarantine_files(self, request, queryset):
        for stored_file in queryset:
            stored_file.quarantine()
            record_action(request.user, ModerationAction.Action.QUARANTINE, stored_file=stored_file)
        self.message_user(request, "Selected files quarantined.", messages.SUCCESS)

    @admin.action(description="Restore selected files")
    def restore_files(self, request, queryset):
        for stored_file in queryset:
            stored_file.restore()
            record_action(request.user, ModerationAction.Action.RESTORE, stored_file=stored_file)
        self.message_user(request, "Selected files restored.", messages.SUCCESS)

    @admin.action(description="Soft-delete selected files")
    def soft_delete_files(self, request, queryset):
        for stored_file in queryset:
            stored_file.soft_delete()
            record_action(request.user, ModerationAction.Action.DELETE, stored_file=stored_file)
        self.message_user(request, "Selected files soft-deleted.", messages.SUCCESS)

    @admin.action(description="Rescan selected files")
    def rescan_files(self, request, queryset):
        for stored_file in queryset:
            if settings.PARAFILES_SCAN_SYNC:
                run_scan_for_file(stored_file.pk)
            else:
                scan_file_task.delay(stored_file.pk)
            record_action(request.user, ModerationAction.Action.RESCAN, stored_file=stored_file)
        self.message_user(request, "Selected files queued for rescanning.", messages.SUCCESS)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("display_name", "owner", "parent", "is_deleted", "created_at")
    list_filter = ("is_deleted", "created_at")
    search_fields = ("name", "owner__username", "owner__email")


@admin.register(PublicShare)
class PublicShareAdmin(admin.ModelAdmin):
    list_display = ("slug", "target_type", "owner", "is_enabled", "created_at", "expires_at")
    list_filter = ("target_type", "is_enabled", "created_at")
    search_fields = ("slug", "owner__username", "owner__email")
    readonly_fields = ("slug", "created_at", "regenerated_at")
    actions = ("disable_shares", "regenerate_shares")

    @admin.action(description="Disable selected shares")
    def disable_shares(self, request, queryset):
        queryset.update(is_enabled=False)
        self.message_user(request, "Selected shares disabled.", messages.SUCCESS)

    @admin.action(description="Regenerate selected share links")
    def regenerate_shares(self, request, queryset):
        for share in queryset:
            share.regenerate_slug()
            record_action(request.user, ModerationAction.Action.REGENERATE_SHARE, share=share)
        self.message_user(request, "Selected share links regenerated.", messages.SUCCESS)


@admin.register(AbuseReport)
class AbuseReportAdmin(admin.ModelAdmin):
    list_display = (
        "category",
        "status",
        "assigned_to",
        "share",
        "stored_file",
        "folder",
        "created_at",
    )
    list_filter = ("category", "status", "assigned_to", "created_at")
    search_fields = ("message", "contact_email", "stored_file__original_filename")
    readonly_fields = ("reporter_ip_hash", "user_agent_hash", "created_at")
    actions = ("mark_reviewing", "mark_resolved", "mark_rejected")

    @admin.action(description="Mark reports as reviewing")
    def mark_reviewing(self, request, queryset):
        queryset.update(status=AbuseReport.Status.REVIEWING)

    @admin.action(description="Resolve reports")
    def mark_resolved(self, request, queryset):
        for report in queryset:
            report.status = AbuseReport.Status.RESOLVED
            report.resolved_at = timezone.now()
            report.handled_by = request.user
            report.save(update_fields=["status", "resolved_at", "handled_by"])
            record_action(request.user, ModerationAction.Action.RESOLVE_REPORT, report=report)

    @admin.action(description="Reject reports")
    def mark_rejected(self, request, queryset):
        queryset.update(status=AbuseReport.Status.REJECTED, resolved_at=timezone.now(), handled_by=request.user)


admin.site.register(UploadSession)
admin.site.register(ScanResult)
admin.site.register(ModerationAction)
admin.site.register(DownloadEvent)
admin.site.register(QuotaOverride)
admin.site.register(RateLimitEvent)
