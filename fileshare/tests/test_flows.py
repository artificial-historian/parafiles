from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from fileshare.checks import parafiles_deploy_checks
from fileshare.models import (
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
from fileshare.services.cleanup import cleanup_expired_uploads
from fileshare.services.email_verification import email_verification_token
from fileshare.services.quotas import effective_quota
from fileshare.services.storage import canonical_signature_payload, private_path


TEST_SIGNATURE_PRIVATE_KEY = "ACpjVaW1y8Pt704l+EWKiqK1vJfJWhRfG6FJY1a+ULs="
TEST_SIGNATURE_PUBLIC_KEY = "Luv36jdzpnhkYMSpZ8NWKZW+JbONOD1Dvd58RkZyY18="


class ParafilesFlowTests(TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[2]
        test_root = workspace / "var" / "test-runs" / uuid.uuid4().hex
        self.storage_root = test_root / "private"
        self.session_root = test_root / "sessions"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.session_root.mkdir(parents=True, exist_ok=True)
        self.override = override_settings(
            PARAFILES_STORAGE_ROOT=self.storage_root,
            PARAFILES_UPLOAD_SESSION_ROOT=self.session_root,
            PARAFILES_SERVE_PRIVATE_DOWNLOADS=True,
            PARAFILES_SCAN_SYNC=True,
            PARAFILES_ALLOW_SCAN_BYPASS=True,
            PARAFILES_CLAMAV_COMMAND="missing-clamscan-for-tests",
            PARAFILES_SIGNATURE_PRIVATE_KEY=TEST_SIGNATURE_PRIVATE_KEY,
            PARAFILES_SIGNATURE_PUBLIC_KEY=TEST_SIGNATURE_PUBLIC_KEY,
        )
        self.override.enable()
        cache.clear()

    def tearDown(self):
        self.override.disable()

    def make_uploader(self, username="uploader") -> User:
        user = User.objects.create_user(username=username, password="pass", is_uploader=True)
        Folder.get_root(user)
        return user

    def make_available_file(self, owner: User, folder: Folder, name="mod.zip", body=b"mod-data"):
        storage_key = f"files/{owner.pk}/{name}"
        path = private_path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return StoredFile.objects.create(
            owner=owner,
            folder=folder,
            original_filename=name,
            storage_key=storage_key,
            size=len(body),
            content_type="application/octet-stream",
            sha256=hashlib.sha256(body).hexdigest(),
            status=StoredFile.Status.AVAILABLE,
        )

    def assert_valid_signature_doc(
        self, body: str, stored_file: StoredFile, filename: str
    ) -> None:
        document = json.loads(body)
        signed = document["signed"]
        self.assertEqual(signed["algorithm"], "Ed25519")
        self.assertEqual(signed["purpose"], "parafiles-file-signature")
        self.assertEqual(signed["version"], 1)
        self.assertEqual(signed["file"]["name"], filename)
        self.assertEqual(signed["file"]["size"], stored_file.size)
        self.assertEqual(signed["file"]["sha256"], stored_file.sha256)

        public_key_bytes = base64.b64decode(document["public_key"], validate=True)
        signature_bytes = base64.b64decode(document["signature"], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(signature_bytes, canonical_signature_payload(signed))

    def totp_token(self, device: TOTPDevice) -> str:
        totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
        return str(totp.token()).zfill(device.digits)

    def test_invite_registration_creates_uploader_and_root_folder(self):
        invitation = Invitation.objects.create(
            email="creator@example.test", expires_at=timezone.now() + timedelta(days=1)
        )
        response = self.client.post(
            reverse("register_invite", args=[invitation.token]),
            {
                "username": "creator",
                "email": "creator@example.test",
                "password1": "A-very-long-test-password-123",
                "password2": "A-very-long-test-password-123",
                "terms_accepted": "on",
                "age_confirmed": "on",
                "upload_review_consent": "on",
                "alpha_notice": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="creator")
        self.assertTrue(user.is_uploader)
        self.assertTrue(user.has_verified_email)
        self.assertTrue(Folder.objects.filter(owner=user, parent=None, name="").exists())
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_invite_registration_sends_verification_when_email_differs_from_invite(self):
        invitation = Invitation.objects.create(
            email="invited@example.test", expires_at=timezone.now() + timedelta(days=1)
        )

        response = self.client.post(
            reverse("register_invite", args=[invitation.token]),
            {
                "username": "creator2",
                "email": "other@example.test",
                "password1": "A-very-long-test-password-123",
                "password2": "A-very-long-test-password-123",
                "terms_accepted": "on",
                "age_confirmed": "on",
                "upload_review_consent": "on",
                "alpha_notice": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="creator2")
        self.assertFalse(user.has_verified_email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["other@example.test"])

    def test_email_verification_marks_current_email_verified(self):
        user = User.objects.create_user(
            username="verifyemail",
            email="verify@example.test",
            password="pass",
            is_uploader=True,
        )
        token = email_verification_token(user, "verify@example.test")

        response = self.client.get(reverse("verify_email", args=[token]))

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.has_verified_email)
        self.assertEqual(user.verified_email, "verify@example.test")

    def test_public_home_and_legal_pages_render(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invitation-only file hosting")
        self.assertContains(response, reverse("login"))
        self.assertContains(response, reverse("terms"))
        self.assertContains(response, reverse("privacy"))
        self.assertContains(response, reverse("copyright_abuse"))
        self.assertContains(response, reverse("contact"))

        for url_name, expected in (
            ("terms", "Terms of Service"),
            ("privacy", "Privacy Policy"),
            ("cookies", "Cookie Policy"),
            ("copyright_abuse", "Copyright and Abuse Reporting"),
            ("contact", "Privacy and GDPR requests"),
            ("abuse_reporting", "Repeat infringers"),
        ):
            page = self.client.get(reverse(url_name))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, expected)

    def test_invite_registration_requires_beta_notice_acknowledgement(self):
        invitation = Invitation.objects.create(expires_at=timezone.now() + timedelta(days=1))

        response = self.client.post(
            reverse("register_invite", args=[invitation.token]),
            {
                "username": "creator",
                "email": "creator@example.test",
                "password1": "A-very-long-test-password-123",
                "password2": "A-very-long-test-password-123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Important Beta Notice")
        self.assertFalse(User.objects.filter(username="creator").exists())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="invites@example.test",
    )
    def test_staff_can_create_and_email_invitation(self):
        staff = User.objects.create_user(
            username="invitestaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderation_invitations"),
            {
                "email": "creator@example.test",
                "expires_in_days": "7",
                "send_email": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get(email="creator@example.test")
        self.assertEqual(invitation.created_by, staff)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["creator@example.test"])
        self.assertIn(reverse("register_invite", args=[invitation.token]), mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_staff_can_resend_invitation_email(self):
        staff = User.objects.create_user(
            username="resendstaff", password="pass", is_staff=True, is_uploader=True
        )
        invitation = Invitation.objects.create(
            email="resend@example.test",
            created_by=staff,
            expires_at=timezone.now() + timedelta(days=3),
        )
        self.client.force_login(staff)

        response = self.client.post(reverse("moderation_invitation_resend", args=[invitation.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(reverse("register_invite", args=[invitation.token]), mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_staff_resend_rejects_expired_invitation(self):
        staff = User.objects.create_user(
            username="expiredresendstaff", password="pass", is_staff=True, is_uploader=True
        )
        invitation = Invitation.objects.create(
            email="expired@example.test",
            created_by=staff,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(staff)

        response = self.client.post(reverse("moderation_invitation_resend", args=[invitation.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_admin_created_invitation_sends_email(self):
        admin_user = User.objects.create_superuser(
            username="inviteadmin", email="admin@example.test", password="pass"
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse("admin:fileshare_invitation_add"),
            {
                "email": "admininvite@example.test",
                "expires_at_0": (timezone.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                "expires_at_1": (timezone.now() + timedelta(days=7)).strftime("%H:%M:%S"),
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get(email="admininvite@example.test")
        self.assertEqual(invitation.created_by, admin_user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(reverse("register_invite", args=[invitation.token]), mail.outbox[0].body)

    def test_chunk_upload_scan_share_and_one_time_download(self):
        user = self.make_uploader()
        self.client.force_login(user)
        body = b"example package"
        start = self.client.post(
            reverse("upload_start"),
            {
                "folder_id": Folder.get_root(user).pk,
                "filename": "../unsafe.zip",
                "size": len(body),
                "content_type": "application/zip",
                "upload_terms": "on",
            },
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(start.status_code, 200)
        payload = start.json()

        chunk = self.client.post(
            payload["chunk_url"],
            {"token": payload["token"], "offset": 0, "chunk": SimpleUploadedFile("unsafe.zip", body)},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(chunk.status_code, 200)
        finalized = self.client.post(
            payload["finalize_url"],
            {"token": payload["token"]},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(finalized.status_code, 200)

        stored_file = StoredFile.objects.get(owner=user)
        self.assertEqual(stored_file.original_filename, "unsafe.zip")
        self.assertEqual(stored_file.status, StoredFile.Status.AVAILABLE)
        self.assertTrue(private_path(f"{stored_file.storage_key}.sig").exists())

        self.client.post(reverse("share_toggle", args=["file", stored_file.pk]), {"enabled": "1"})
        share = PublicShare.objects.get(stored_file=stored_file)
        prepare = self.client.post(reverse("prepare_download", args=[share.slug]))
        self.assertEqual(prepare.status_code, 302)
        download = self.client.get(prepare["Location"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), body)
        reused = self.client.get(prepare["Location"])
        self.assertEqual(reused.status_code, 403)

        prepare_signature = self.client.post(reverse("prepare_signature_download", args=[share.slug]))
        self.assertEqual(prepare_signature.status_code, 302)
        signature = self.client.get(prepare_signature["Location"])
        self.assertEqual(signature.status_code, 200)
        signature_body = b"".join(signature.streaming_content).decode("utf-8")
        self.assert_valid_signature_doc(signature_body, stored_file, "unsafe.zip")

    def test_upload_start_requires_upload_terms_acknowledgement(self):
        user = self.make_uploader()
        self.client.force_login(user)

        response = self.client.post(
            reverse("upload_start"),
            {
                "folder_id": Folder.get_root(user).pk,
                "filename": "no-consent.zip",
                "size": 4,
                "content_type": "application/zip",
            },
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("upload_terms", response.json()["errors"])

    def test_quick_share_requires_login_and_renders_for_uploader(self):
        response = self.client.get(reverse("quick_share"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("login")))
        self.assertIn("next=/share/", response["Location"])

        user = self.make_uploader()
        self.client.force_login(user)
        response = self.client.get(reverse("quick_share"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Drop files here")
        self.assertContains(response, reverse("quick_share_folders"))
        self.assertContains(response, reverse("upload_start"))

    def test_quick_share_finalize_creates_enabled_file_share(self):
        user = self.make_uploader()
        self.client.force_login(user)
        body = b"quick share package"
        start = self.client.post(
            reverse("upload_start"),
            {
                "folder_id": Folder.get_root(user).pk,
                "filename": "quick.zip",
                "size": len(body),
                "content_type": "application/zip",
                "upload_terms": "on",
            },
            HTTP_ACCEPT="application/json",
        )
        payload = start.json()
        chunk = self.client.post(
            payload["chunk_url"],
            {"token": payload["token"], "offset": 0, "chunk": SimpleUploadedFile("quick.zip", body)},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(chunk.status_code, 200)

        finalized = self.client.post(
            payload["finalize_url"],
            {"token": payload["token"], "quick_share": "1"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(finalized.status_code, 200)
        finalized_payload = finalized.json()
        stored_file = StoredFile.objects.get(owner=user, original_filename="quick.zip")
        share = PublicShare.objects.get(stored_file=stored_file)
        self.assertTrue(share.is_enabled)
        self.assertEqual(finalized_payload["file_id"], stored_file.pk)
        self.assertIn(reverse("public_file", args=[share.slug]), finalized_payload["share_url"])

    def test_public_share_slugs_and_routes_are_short(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        folder = Folder.objects.create(owner=user, parent=root, name="Published")
        stored_file = self.make_available_file(user, folder, name="short.zip")
        file_share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        folder_share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FOLDER, folder=folder
        )

        self.assertEqual(len(file_share.slug), 16)
        self.assertEqual(len(folder_share.slug), 16)
        self.assertEqual(reverse("public_file", args=[file_share.slug]), f"/f/{file_share.slug}/")
        self.assertEqual(reverse("public_folder", args=[folder_share.slug]), f"/d/{folder_share.slug}/")
        self.assertEqual(self.client.get(f"/file/{file_share.slug}/").status_code, 200)
        self.assertEqual(self.client.get(f"/folder/{folder_share.slug}/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/d/{folder_share.slug}/f/{stored_file.pk}/").status_code, 404
        )

        moved = Folder.objects.create(owner=user, parent=root, name="Moved")
        stored_file.folder = moved
        stored_file.save(update_fields=["folder", "updated_at"])

        self.assertEqual(
            self.client.get(reverse("public_file", args=[file_share.slug])).status_code, 200
        )

    def test_quick_share_folder_apis_update_uploads_and_files(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        target = Folder.objects.create(owner=user, parent=root, name="Shared")
        stored_file = self.make_available_file(user, root, name="move-me.zip")
        self.client.force_login(user)

        folders = self.client.get(reverse("quick_share_folders"), HTTP_ACCEPT="application/json")
        self.assertEqual(folders.status_code, 200)
        self.assertIn("/Shared", [item["path"] for item in folders.json()["folders"]])

        start = self.client.post(
            reverse("upload_start"),
            {
                "folder_id": root.pk,
                "filename": "queued.zip",
                "size": 12,
                "content_type": "application/zip",
                "upload_terms": "on",
            },
            HTTP_ACCEPT="application/json",
        )
        upload_payload = start.json()
        moved_upload = self.client.post(
            reverse("quick_share_upload_folder", args=[upload_payload["upload_id"]]),
            {"token": upload_payload["token"], "folder_id": target.pk},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(moved_upload.status_code, 200)
        self.assertEqual(moved_upload.json()["folder"]["path"], "/Shared")
        session = UploadSession.objects.get(upload_id=upload_payload["upload_id"])
        self.assertEqual(session.folder, target)

        moved_file = self.client.post(
            reverse("quick_share_file_folder", args=[stored_file.pk]),
            {"folder_id": target.pk},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(moved_file.status_code, 200)
        stored_file.refresh_from_db()
        self.assertEqual(stored_file.folder, target)

    def test_upload_rejects_out_of_order_chunk(self):
        user = self.make_uploader()
        self.client.force_login(user)
        body = b"example package"
        start = self.client.post(
            reverse("upload_start"),
            {
                "folder_id": Folder.get_root(user).pk,
                "filename": "mod.zip",
                "size": len(body),
                "content_type": "application/zip",
                "upload_terms": "on",
            },
            HTTP_ACCEPT="application/json",
        )
        payload = start.json()
        response = self.client.post(
            payload["chunk_url"],
            {"token": payload["token"], "offset": 5, "chunk": SimpleUploadedFile("mod.zip", body)},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["bytes_received"], 0)

    def test_upload_status_reports_resume_offset(self):
        user = self.make_uploader()
        self.client.force_login(user)
        body = b"split package"
        start = self.client.post(
            reverse("upload_start"),
            {
                "folder_id": Folder.get_root(user).pk,
                "filename": "resume.zip",
                "size": len(body),
                "content_type": "application/zip",
                "upload_terms": "on",
            },
            HTTP_ACCEPT="application/json",
        )
        payload = start.json()
        first_part = body[:5]
        chunk = self.client.post(
            payload["chunk_url"],
            {
                "token": payload["token"],
                "offset": 0,
                "chunk": SimpleUploadedFile("resume.zip", first_part),
            },
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(chunk.status_code, 200)

        status = self.client.get(payload["status_url"], HTTP_X_UPLOAD_TOKEN=payload["token"])
        wrong_token = self.client.get(payload["status_url"], HTTP_X_UPLOAD_TOKEN="wrong")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["bytes_received"], len(first_part))
        self.assertEqual(status.json()["status"], "uploading")
        self.assertEqual(wrong_token.status_code, 404)

    def test_active_uploads_list_exposes_resumable_sessions(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        session = UploadSession.objects.create(
            owner=user,
            folder=root,
            original_filename="resume-me.zip",
            size=100,
            content_type="application/zip",
            temp_path="resume-me.part",
            bytes_received=40,
            status=UploadSession.Status.UPLOADING,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        UploadSession.objects.create(
            owner=user,
            folder=root,
            original_filename="done.zip",
            size=10,
            content_type="application/zip",
            temp_path="done.part",
            bytes_received=10,
            status=UploadSession.Status.FINALIZED,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.client.force_login(user)

        response = self.client.get(reverse("upload_active"), HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        uploads = response.json()["uploads"]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["upload_id"], str(session.upload_id))
        self.assertEqual(uploads[0]["filename"], "resume-me.zip")
        self.assertEqual(uploads[0]["bytes_received"], 40)
        self.assertEqual(uploads[0]["folder_path"], "/")

    def test_cleanup_expired_upload_session_removes_staged_file(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        temp_file = self.session_root / "expired.part"
        temp_file.write_bytes(b"staged")
        session = UploadSession.objects.create(
            owner=user,
            folder=root,
            original_filename="expired.zip",
            size=6,
            content_type="application/zip",
            temp_path="expired.part",
            bytes_received=6,
            status=UploadSession.Status.UPLOADING,
            expires_at=timezone.now() - timedelta(minutes=5),
        )

        result = cleanup_expired_uploads(orphan_age_seconds=86400)

        session.refresh_from_db()
        self.assertEqual(session.status, UploadSession.Status.EXPIRED)
        self.assertTrue(not temp_file.exists() or temp_file.stat().st_size == 0)
        self.assertEqual(result.expired_sessions, 1)
        self.assertEqual(result.temp_files_deleted, 1)
        self.assertEqual(result.bytes_deleted, 6)

    def test_cleanup_removes_old_orphan_upload_parts_but_keeps_active_parts(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        orphan = self.session_root / "orphan.part"
        active = self.session_root / "active.part"
        orphan.write_bytes(b"orphan")
        active.write_bytes(b"active")
        old_timestamp = (timezone.now() - timedelta(hours=2)).timestamp()
        orphan.touch()
        active.touch()

        os.utime(orphan, (old_timestamp, old_timestamp))
        os.utime(active, (old_timestamp, old_timestamp))
        UploadSession.objects.create(
            owner=user,
            folder=root,
            original_filename="active.zip",
            size=6,
            content_type="application/zip",
            temp_path="active.part",
            bytes_received=3,
            status=UploadSession.Status.UPLOADING,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        result = cleanup_expired_uploads(orphan_age_seconds=60)

        self.assertTrue(not orphan.exists() or orphan.stat().st_size == 0)
        self.assertTrue(active.exists())
        self.assertEqual(result.orphan_temp_files_deleted, 1)
        self.assertEqual(result.bytes_deleted, 6)

    def test_dashboard_exposes_file_and_folder_management_controls(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        Folder.objects.create(owner=user, parent=root, name="Packages")
        self.make_available_file(user, root, name="demo.zip")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("folder_rename", args=[Folder.objects.get(name="Packages").pk]))
        self.assertContains(response, reverse("file_rename", args=[StoredFile.objects.get(original_filename="demo.zip").pk]))
        self.assertContains(response, "Move")

    def test_files_and_shares_page_lists_files_folders_and_share_actions(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        folder = Folder.objects.create(owner=user, parent=root, name="Packages")
        stored_file = self.make_available_file(user, root, name="demo.zip")
        file_share = PublicShare.objects.create(
            owner=user,
            target_type=PublicShare.TargetType.FILE,
            stored_file=stored_file,
        )
        folder_share = PublicShare.objects.create(
            owner=user,
            target_type=PublicShare.TargetType.FOLDER,
            folder=folder,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("files_and_shares"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Files & Shares")
        self.assertContains(response, "Packages")
        self.assertContains(response, "demo.zip")
        self.assertContains(response, reverse("files_and_shares") + f"?folder={folder.pk}")
        self.assertContains(response, reverse("folder_move", args=[folder.pk]))
        self.assertContains(response, reverse("folder_delete", args=[folder.pk]))
        self.assertContains(response, reverse("file_move", args=[stored_file.pk]))
        self.assertContains(response, reverse("file_delete", args=[stored_file.pk]))
        self.assertContains(response, reverse("share_regenerate", args=[file_share.pk]))
        self.assertContains(response, reverse("share_regenerate", args=[folder_share.pk]))
        self.assertContains(response, reverse("public_file", args=[file_share.slug]))
        self.assertContains(response, reverse("public_folder", args=[folder_share.slug]))

    def test_files_and_shares_actions_return_to_requested_page(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        source = Folder.objects.create(owner=user, parent=root, name="Source")
        target = Folder.objects.create(owner=user, parent=root, name="Target")
        stored_file = self.make_available_file(user, source, name="move-me.zip")
        self.client.force_login(user)
        next_url = f"{reverse('files_and_shares')}?folder={source.pk}"

        moved = self.client.post(
            reverse("file_move", args=[stored_file.pk]),
            {"target_folder_id": target.pk, "next": next_url},
        )
        self.assertEqual(moved.status_code, 302)
        self.assertEqual(moved["Location"], next_url)
        stored_file.refresh_from_db()
        self.assertEqual(stored_file.folder, target)

        created = self.client.post(
            reverse("folder_create"),
            {"parent_id": source.pk, "name": "Nested", "next": next_url},
        )
        self.assertEqual(created.status_code, 302)
        self.assertEqual(created["Location"], next_url)
        self.assertTrue(Folder.objects.filter(owner=user, parent=source, name="Nested").exists())

    def test_uploader_can_edit_file_metadata_and_public_page_shows_it(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user), name="plain.zip")
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("file_metadata", args=[stored_file.pk]),
            {
                "title": "Modern Kitchen Set",
                "description": "Counters and clutter for a small apartment.",
                "version": "1.2.0",
                "game_version": "Paralives 1.0",
                "changelog": "Updated swatches.",
            },
        )

        self.assertEqual(response.status_code, 302)
        stored_file.refresh_from_db()
        self.assertEqual(stored_file.title, "Modern Kitchen Set")
        public = self.client.get(reverse("public_file", args=[share.slug]))
        self.assertContains(public, "Modern Kitchen Set")
        self.assertContains(public, "Paralives 1.0")
        self.assertContains(public, "Updated swatches.")

    def test_public_file_page_shows_scan_download_stats_and_signature_action(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user), name="plain.zip")
        stored_file.download_count = 4
        stored_file.save(update_fields=["download_count"])
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        DownloadEvent.objects.create(
            stored_file=stored_file,
            share=share,
            ip_hash="ip",
            user_agent_hash="ua",
            bytes_served=stored_file.size,
            outcome=DownloadEvent.Outcome.ALLOWED,
        )

        response = self.client.get(reverse("public_file", args=[share.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Malware scan")
        self.assertContains(response, "No malware detected")
        self.assertContains(response, "Downloads")
        self.assertContains(response, "4")
        self.assertContains(response, "Last downloaded")
        self.assertContains(response, "Download .sig")
        self.assertContains(response, reverse("prepare_signature_download", args=[share.slug]))
        self.assertNotContains(response, "SHA-256")
        self.assertNotContains(response, ">Available<")

    def test_signature_download_serves_sidecar_without_counting_file_download(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user), name="plain.zip")
        private_path(f"{stored_file.storage_key}.sig").write_bytes(b"signature-bytes")
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )

        prepared = self.client.post(reverse("prepare_signature_download", args=[share.slug]))
        self.assertEqual(prepared.status_code, 302)
        response = self.client.get(prepared["Location"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"signature-bytes")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="plain.zip.sig"; filename*=UTF-8\'\'plain.zip.sig',
        )
        stored_file.refresh_from_db()
        self.assertEqual(stored_file.download_count, 0)
        self.assertFalse(
            DownloadEvent.objects.filter(
                stored_file=stored_file,
                outcome=DownloadEvent.Outcome.ALLOWED,
            ).exists()
        )

    def test_signature_download_generates_missing_sidecar_for_existing_file(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user), name="legacy.zip")
        signature_path = private_path(f"{stored_file.storage_key}.sig")
        self.assertFalse(signature_path.exists())
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )

        prepared = self.client.post(reverse("prepare_signature_download", args=[share.slug]))
        self.assertEqual(prepared.status_code, 302)
        response = self.client.get(prepared["Location"])

        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(signature_path.exists())
        self.assert_valid_signature_doc(body, stored_file, "legacy.zip")

    def test_account_settings_show_usage_and_update_email(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        stored_file = self.make_available_file(user, root, name="demo.zip")
        DownloadEvent.objects.create(
            stored_file=stored_file,
            ip_hash="ip",
            user_agent_hash="ua",
            bytes_served=stored_file.size,
            outcome=DownloadEvent.Outcome.ALLOWED,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("account_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "demo.zip")
        self.assertContains(response, "Storage used")

        post = self.client.post(reverse("account_settings"), {"email": "new@example.test"})
        self.assertEqual(post.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.test")
        self.assertFalse(user.has_verified_email)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_account_settings_keeps_verified_email_until_new_email_verified(self):
        user = self.make_uploader()
        user.email = "old@example.test"
        user.verified_email = "old@example.test"
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email", "verified_email", "email_verified_at"])
        self.client.force_login(user)

        response = self.client.post(reverse("account_settings"), {"email": "new@example.test"})

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.test")
        self.assertEqual(user.pending_email, "new@example.test")
        self.assertTrue(user.has_verified_email)
        self.assertEqual(len(mail.outbox), 1)
        token = email_verification_token(user, "new@example.test")

        verify = self.client.get(reverse("verify_email", args=[token]))

        self.assertEqual(verify.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.email, "new@example.test")
        self.assertEqual(user.pending_email, "")
        self.assertTrue(user.has_verified_email)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_only_sends_for_verified_email(self):
        verified = User.objects.create_user(
            username="verifiedreset",
            email="verified@example.test",
            password="pass",
            is_uploader=True,
        )
        verified.verified_email = "verified@example.test"
        verified.email_verified_at = timezone.now()
        verified.save(update_fields=["verified_email", "email_verified_at"])
        User.objects.create_user(
            username="unverifiedreset",
            email="unverified@example.test",
            password="pass",
            is_uploader=True,
        )

        self.client.post(reverse("password_reset"), {"email": "unverified@example.test"})
        self.assertEqual(len(mail.outbox), 0)

        self.client.post(reverse("password_reset"), {"email": "verified@example.test"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["verified@example.test"])

    def test_account_settings_show_scan_status(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user), name="scanned.zip")
        ScanResult.objects.create(
            stored_file=stored_file,
            engine=ScanResult.Engine.CLAMAV,
            status=ScanResult.Status.CLEAN,
            signature="",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scan Status")
        self.assertContains(response, "ClamAV: Clean")

    @override_settings(PARAFILES_ADMIN_2FA_REQUIRED=True)
    def test_staff_2fa_redirects_unverified_staff_to_setup(self):
        staff = User.objects.create_user(
            username="needs2fa", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("moderation_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("staff_2fa_setup")))
        self.assertIn("next=%2Fmoderation%2F", response["Location"])

    @override_settings(PARAFILES_ADMIN_2FA_REQUIRED=True)
    def test_staff_can_enroll_totp_and_access_moderation(self):
        staff = User.objects.create_user(
            username="enroll2fa", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        setup = self.client.get(reverse("staff_2fa_setup"))
        self.assertEqual(setup.status_code, 200)
        device = TOTPDevice.objects.get(user=staff, confirmed=False)
        token = self.totp_token(device)

        enabled = self.client.post(
            reverse("staff_2fa_setup"),
            {"token": token, "next": reverse("moderation_dashboard")},
        )

        self.assertEqual(enabled.status_code, 302)
        self.assertEqual(enabled["Location"], reverse("moderation_dashboard"))
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        response = self.client.get(reverse("moderation_dashboard"))
        self.assertEqual(response.status_code, 200)

    @override_settings(PARAFILES_ADMIN_2FA_REQUIRED=True)
    def test_staff_with_totp_device_must_verify_before_moderation(self):
        staff = User.objects.create_user(
            username="verify2fa", password="pass", is_staff=True, is_uploader=True
        )
        device = TOTPDevice.objects.create(user=staff, name="staff", confirmed=True)
        self.client.force_login(staff)

        blocked = self.client.get(reverse("moderation_dashboard"))
        self.assertEqual(blocked.status_code, 302)
        self.assertTrue(blocked["Location"].startswith(reverse("staff_2fa_verify")))

        verified = self.client.post(
            reverse("staff_2fa_verify"),
            {"token": self.totp_token(device), "next": reverse("moderation_dashboard")},
        )
        self.assertEqual(verified.status_code, 302)
        self.assertEqual(verified["Location"], reverse("moderation_dashboard"))
        response = self.client.get(reverse("moderation_dashboard"))
        self.assertEqual(response.status_code, 200)

    @override_settings(PARAFILES_ADMIN_2FA_REQUIRED=True)
    def test_uploader_dashboard_does_not_require_staff_2fa(self):
        user = self.make_uploader()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)

    def test_share_actions_accept_only_safe_next_redirects(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        self.client.force_login(user)

        safe = self.client.post(
            reverse("share_toggle", args=["file", stored_file.pk]),
            {"enabled": "0", "next": reverse("account_settings")},
        )
        self.assertEqual(safe["Location"], reverse("account_settings"))

        share.is_enabled = True
        share.save(update_fields=["is_enabled"])
        unsafe = self.client.post(
            reverse("share_toggle", args=["file", stored_file.pk]),
            {"enabled": "0", "next": "https://evil.example/"},
        )
        self.assertEqual(unsafe["Location"], f"{reverse('dashboard')}?folder={stored_file.folder_id}")

    def test_uploader_can_set_and_clear_share_expiration(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        self.client.force_login(user)
        expires_at = timezone.now() + timedelta(days=2)

        response = self.client.post(
            reverse("share_update", args=[share.pk]),
            {
                "is_enabled": "on",
                "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M"),
                "next": reverse("account_settings"),
            },
        )

        self.assertEqual(response.status_code, 302)
        share.refresh_from_db()
        self.assertTrue(share.is_enabled)
        self.assertIsNotNone(share.expires_at)

        clear = self.client.post(
            reverse("share_update", args=[share.pk]),
            {"is_enabled": "on", "clear_expiration": "on"},
        )
        self.assertEqual(clear.status_code, 302)
        share.refresh_from_db()
        self.assertIsNone(share.expires_at)

    def test_expired_share_returns_unavailable(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user,
            target_type=PublicShare.TargetType.FILE,
            stored_file=stored_file,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get(reverse("public_file", args=[share.slug]))

        self.assertEqual(response.status_code, 404)

    def test_public_folder_share_does_not_expose_siblings_or_parent_path(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        parent = Folder.objects.create(owner=user, parent=root, name="Parent Secret")
        shared = Folder.objects.create(owner=user, parent=parent, name="Published")
        sibling = Folder.objects.create(owner=user, parent=parent, name="Private")
        public_file = self.make_available_file(user, shared, name="public.zip")
        self.make_available_file(user, sibling, name="private.zip")
        share = PublicShare.objects.create(
            owner=user,
            target_type=PublicShare.TargetType.FOLDER,
            folder=shared,
        )

        response = self.client.get(reverse("public_folder", args=[share.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, public_file.original_filename)
        self.assertContains(response, f"Shared by {user.username}")
        self.assertContains(response, reverse("prepare_download", args=[share.slug]))
        self.assertContains(response, f'name="file_id" value="{public_file.pk}"')
        self.assertNotContains(response, f"/d/{share.slug}/f/{public_file.pk}/")
        self.assertNotContains(response, f"/download/prepare/{share.slug}/{public_file.pk}/")
        self.assertNotContains(response, "private.zip")
        self.assertNotContains(response, "Parent Secret")

    def test_folder_shared_file_downloads_and_reports_file(self):
        user = self.make_uploader(username="folderowner")
        root = Folder.get_root(user)
        shared = Folder.objects.create(owner=user, parent=root, name="Published")
        stored_file = self.make_available_file(user, shared, name="inside.zip")
        share = PublicShare.objects.create(
            owner=user,
            target_type=PublicShare.TargetType.FOLDER,
            folder=shared,
        )

        folder_page = self.client.get(reverse("public_folder", args=[share.slug]))
        self.assertContains(folder_page, "inside.zip")
        self.assertContains(folder_page, reverse("prepare_download", args=[share.slug]))
        self.assertContains(folder_page, f'name="file_id" value="{stored_file.pk}"')
        self.assertNotContains(folder_page, f"/download/prepare/{share.slug}/{stored_file.pk}/")
        self.assertNotContains(folder_page, f"/d/{share.slug}/f/{stored_file.pk}/")

        prepared = self.client.post(
            reverse("prepare_download", args=[share.slug]), {"file_id": stored_file.pk}
        )
        self.assertEqual(prepared.status_code, 302)

        report = self.client.post(
            reverse("report_share", args=[share.slug]),
            {
                "category": AbuseReport.Category.MALWARE,
                "message": "This folder share appears unsafe.",
            },
        )

        self.assertEqual(report.status_code, 302)
        abuse_report = AbuseReport.objects.get()
        self.assertEqual(abuse_report.share, share)
        self.assertIsNone(abuse_report.stored_file)
        self.assertEqual(abuse_report.folder, shared)

    def test_hidden_file_public_link_returns_not_found(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        stored_file.hide()
        response = self.client.get(reverse("public_file", args=[share.slug]))
        self.assertEqual(response.status_code, 404)

    def test_disabled_share_returns_not_found(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        share.is_enabled = False
        share.save(update_fields=["is_enabled"])
        response = self.client.get(reverse("public_file", args=[share.slug]))
        self.assertEqual(response.status_code, 404)

    def test_deleted_parent_folder_hides_nested_file_link(self):
        user = self.make_uploader()
        root = Folder.get_root(user)
        parent = Folder.objects.create(owner=user, parent=root, name="Parent")
        child = Folder.objects.create(owner=user, parent=parent, name="Child")
        stored_file = self.make_available_file(user, child)
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        parent.soft_delete()
        response = self.client.get(reverse("public_file", args=[share.slug]))
        self.assertEqual(response.status_code, 404)

    def test_downloader_can_report_public_share(self):
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        response = self.client.post(
            reverse("report_share", args=[share.slug]),
            {
                "category": AbuseReport.Category.MALWARE,
                "message": "This file appears unsafe.",
                "contact_email": "reporter@example.test",
            },
        )
        self.assertEqual(response.status_code, 302)
        report = AbuseReport.objects.get()
        self.assertEqual(report.stored_file, stored_file)
        self.assertEqual(report.status, AbuseReport.Status.OPEN)

    def test_staff_can_assign_note_and_resolve_report(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="staff", password="pass", is_staff=True, is_uploader=True
        )
        stored_file = self.make_available_file(uploader, Folder.get_root(uploader))
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        report = AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.OTHER,
            message="Please review",
            reporter_ip_hash="ip",
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderate_report_update", args=[report.pk]),
            {
                "status": AbuseReport.Status.RESOLVED,
                "assigned_to": staff.pk,
                "staff_notes": "Confirmed and handled.",
            },
        )

        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.status, AbuseReport.Status.RESOLVED)
        self.assertEqual(report.assigned_to, staff)
        self.assertEqual(report.handled_by, staff)
        self.assertIsNotNone(report.resolved_at)
        self.assertEqual(report.staff_notes, "Confirmed and handled.")

    def test_staff_can_hide_and_restore_folder(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="folderstaff", password="pass", is_staff=True, is_uploader=True
        )
        folder = Folder.objects.create(owner=uploader, parent=Folder.get_root(uploader), name="Shared")
        self.client.force_login(staff)

        hide = self.client.post(reverse("moderate_folder", args=[folder.pk, "hide"]))
        self.assertEqual(hide.status_code, 302)
        folder.refresh_from_db()
        self.assertTrue(folder.is_deleted)

        restore = self.client.post(reverse("moderate_folder", args=[folder.pk, "restore"]))
        self.assertEqual(restore.status_code, 302)
        folder.refresh_from_db()
        self.assertFalse(folder.is_deleted)
        self.assertTrue(
            ModerationAction.objects.filter(
                actor=staff, folder=folder, action=ModerationAction.Action.RESTORE
            ).exists()
        )

    def test_staff_can_purge_folder_tree(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="purgestaff", password="pass", is_staff=True, is_uploader=True
        )
        root = Folder.get_root(uploader)
        folder = Folder.objects.create(owner=uploader, parent=root, name="Bad")
        child = Folder.objects.create(owner=uploader, parent=folder, name="Nested")
        stored_file = self.make_available_file(uploader, child, name="bad.zip")
        file_path = private_path(stored_file.storage_key)
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        self.client.force_login(staff)

        response = self.client.post(reverse("moderate_folder", args=[folder.pk, "purge"]))

        self.assertEqual(response.status_code, 302)
        stored_file.refresh_from_db()
        share.refresh_from_db()
        folder.refresh_from_db()
        child.refresh_from_db()
        self.assertEqual(stored_file.status, StoredFile.Status.DELETED)
        self.assertTrue(not file_path.exists() or file_path.stat().st_size == 0)
        self.assertFalse(share.is_enabled)
        self.assertTrue(folder.is_deleted)
        self.assertTrue(child.is_deleted)

    def test_moderation_dashboard_filters_reports_files_and_folders(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="filterstaff", password="pass", is_staff=True, is_uploader=True
        )
        root = Folder.get_root(uploader)
        folder = Folder.objects.create(owner=uploader, parent=root, name="Kitchen")
        stored_file = self.make_available_file(uploader, folder, name="kitchen-pack.zip")
        stored_file.title = "Kitchen Pack"
        stored_file.save(update_fields=["title"])
        self.make_available_file(uploader, root, name="bathroom-pack.zip")
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.COPYRIGHT,
            message="Kitchen pack copies another creator.",
            reporter_ip_hash="ip",
        )
        self.client.force_login(staff)

        response = self.client.get(
            reverse("moderation_dashboard"),
            {
                "q": "Kitchen",
                "report_status": AbuseReport.Status.OPEN,
                "file_status": StoredFile.Status.AVAILABLE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kitchen pack copies another creator.")
        self.assertContains(response, "kitchen-pack.zip")
        self.assertContains(response, "/Kitchen")
        self.assertNotContains(response, "bathroom-pack.zip")

    def test_report_detail_shows_related_reports_and_target_controls(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="detailstaff", password="pass", is_staff=True, is_uploader=True
        )
        stored_file = self.make_available_file(uploader, Folder.get_root(uploader), name="reported.zip")
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        report = AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.MALWARE,
            message="Primary malware report",
            reporter_ip_hash="ip1",
        )
        related = AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.OTHER,
            message="Second report for the same file",
            reporter_ip_hash="ip2",
        )
        ModerationAction.objects.create(
            actor=staff,
            stored_file=stored_file,
            report=report,
            action=ModerationAction.Action.HIDE,
            reason="Initial triage",
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("moderation_report_detail", args=[report.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "reported.zip")
        self.assertContains(response, f"Report {related.pk}")
        self.assertContains(response, "Second report for the same file")
        self.assertContains(response, "Initial triage")
        self.assertContains(response, reverse("moderate_file", args=[stored_file.pk, "quarantine"]))
        self.assertContains(response, reverse("moderate_share", args=[share.pk, "regenerate_share"]))

    def test_staff_can_disable_restore_and_regenerate_share(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="sharestaff", password="pass", is_staff=True, is_uploader=True
        )
        stored_file = self.make_available_file(uploader, Folder.get_root(uploader), name="shared.zip")
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        old_slug = share.slug
        self.client.force_login(staff)

        disabled = self.client.post(
            reverse("moderate_share", args=[share.pk, "hide"]),
            {"reason": "Reported link should be disabled."},
        )
        self.assertEqual(disabled.status_code, 302)
        share.refresh_from_db()
        self.assertFalse(share.is_enabled)
        self.assertEqual(self.client.get(reverse("public_file", args=[old_slug])).status_code, 404)
        self.assertTrue(
            ModerationAction.objects.filter(
                actor=staff,
                share=share,
                action=ModerationAction.Action.HIDE,
                reason="Reported link should be disabled.",
            ).exists()
        )

        restored = self.client.post(reverse("moderate_share", args=[share.pk, "restore"]))
        self.assertEqual(restored.status_code, 302)
        share.refresh_from_db()
        self.assertTrue(share.is_enabled)
        self.assertEqual(self.client.get(reverse("public_file", args=[old_slug])).status_code, 200)

        regenerated = self.client.post(
            reverse("moderate_share", args=[share.pk, "regenerate_share"]),
            {"reason": "Rotate exposed slug."},
        )
        self.assertEqual(regenerated.status_code, 302)
        share.refresh_from_db()
        self.assertNotEqual(share.slug, old_slug)
        self.assertEqual(self.client.get(reverse("public_file", args=[old_slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("public_file", args=[share.slug])).status_code, 200)
        action = ModerationAction.objects.get(
            actor=staff,
            share=share,
            action=ModerationAction.Action.REGENERATE_SHARE,
            reason="Rotate exposed slug.",
        )
        self.assertEqual(action.metadata["old_slug"], old_slug)
        self.assertEqual(action.metadata["new_slug"], share.slug)

    def test_staff_can_view_and_filter_moderation_action_log(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="auditstaff", password="pass", is_staff=True, is_uploader=True
        )
        other_staff = User.objects.create_user(
            username="otheraudit", password="pass", is_staff=True, is_uploader=True
        )
        stored_file = self.make_available_file(uploader, Folder.get_root(uploader), name="audit.zip")
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        report = AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.OTHER,
            message="Audit report message",
            reporter_ip_hash="ip",
        )
        ModerationAction.objects.create(
            actor=staff,
            action=ModerationAction.Action.HIDE,
            stored_file=stored_file,
            share=share,
            report=report,
            reason="Matched audit.zip report.",
        )
        ModerationAction.objects.create(
            actor=other_staff,
            action=ModerationAction.Action.RESTORE,
            stored_file=stored_file,
            reason="Other action should be filtered out.",
        )
        self.client.force_login(staff)

        response = self.client.get(
            reverse("moderation_action_log"),
            {
                "q": "audit.zip",
                "action": ModerationAction.Action.HIDE,
                "actor": staff.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Matched audit.zip report.")
        self.assertContains(response, "audit.zip")
        self.assertContains(response, f"Report {report.pk}")
        self.assertContains(response, share.slug)
        self.assertNotContains(response, "Other action should be filtered out.")

    def test_staff_can_view_and_filter_rate_limit_events(self):
        staff = User.objects.create_user(
            username="ratestaff", password="pass", is_staff=True, is_uploader=True
        )
        RateLimitEvent.objects.create(
            scope="download:prepare",
            key="ip:abc123",
            ip_hash="abc123",
            user_agent_hash="ua123",
            count=12,
            action=RateLimitEvent.Action.BLOCK,
        )
        RateLimitEvent.objects.create(
            scope="public:page",
            key="ip:other",
            ip_hash="other",
            count=3,
            action=RateLimitEvent.Action.WARN,
        )
        self.client.force_login(staff)

        response = self.client.get(
            reverse("moderation_rate_limit_events"),
            {
                "q": "abc123",
                "scope": "download",
                "action": RateLimitEvent.Action.BLOCK,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "download:prepare")
        self.assertContains(response, "ip:abc123")
        self.assertContains(response, "ua123")
        self.assertContains(response, "Blocks")
        self.assertNotContains(response, "public:page")

    def test_staff_can_view_operations_health(self):
        staff = User.objects.create_user(
            username="opsstaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("moderation_operations_health"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operations Health")
        self.assertContains(response, "Database")
        self.assertContains(response, "Cache")
        self.assertContains(response, "Private storage")
        self.assertContains(response, "Upload staging")
        self.assertContains(response, "ClamAV")
        self.assertContains(response, "VirusTotal")
        self.assertContains(response, "Protected downloads")
        self.assertContains(response, "Celery broker")

    def test_staff_can_view_email_diagnostics(self):
        staff = User.objects.create_user(
            username="mailstaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("moderation_email_diagnostics"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email Diagnostics")
        self.assertContains(response, "Email backend")
        self.assertContains(response, "SMTP host")
        self.assertContains(response, "SMTP password")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="diagnostics@example.test",
    )
    def test_staff_can_send_email_diagnostic(self):
        staff = User.objects.create_user(
            username="mailsendstaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderation_email_diagnostics"),
            {
                "recipient": "recipient@example.test",
                "subject": "Diagnostic subject",
                "body": "Diagnostic body",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Backend accepted 1 message.")
        self.assertContains(response, "recipient@example.test")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, "diagnostics@example.test")
        self.assertEqual(mail.outbox[0].to, ["recipient@example.test"])
        self.assertEqual(mail.outbox[0].subject, "Diagnostic subject")

    @override_settings(PARAFILES_ALLOW_SCAN_BYPASS=False)
    def test_operations_health_flags_required_missing_clamav_as_error(self):
        staff = User.objects.create_user(
            username="opserrorstaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("moderation_operations_health"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Error")
        self.assertContains(response, "missing-clamscan-for-tests not found")

    def test_staff_can_suspend_restore_and_disable_uploader_shares(self):
        uploader = self.make_uploader(username="problemcreator")
        uploader.email = "problem@example.test"
        uploader.save(update_fields=["email"])
        staff = User.objects.create_user(
            username="userstaff", password="pass", is_staff=True, is_uploader=True
        )
        stored_file = self.make_available_file(uploader, Folder.get_root(uploader), name="problem.zip")
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        self.client.force_login(staff)

        list_response = self.client.get(
            reverse("moderation_users"), {"q": "problem", "state": "uploader"}
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "problemcreator")
        self.assertContains(list_response, "problem.zip", count=0)

        suspended = self.client.post(
            reverse("moderate_user", args=[uploader.pk, "suspend_user"]),
            {"reason": "Confirmed abusive uploader."},
        )
        self.assertEqual(suspended.status_code, 302)
        uploader.refresh_from_db()
        share.refresh_from_db()
        self.assertFalse(uploader.is_active)
        self.assertFalse(uploader.is_uploader)
        self.assertFalse(share.is_enabled)
        self.assertEqual(self.client.get(reverse("public_file", args=[share.slug])).status_code, 404)
        action = ModerationAction.objects.get(
            actor=staff,
            target_user=uploader,
            action=ModerationAction.Action.SUSPEND_USER,
            reason="Confirmed abusive uploader.",
        )
        self.assertEqual(action.metadata["disabled_shares"], 1)

        restored = self.client.post(reverse("moderate_user", args=[uploader.pk, "restore_user"]))
        self.assertEqual(restored.status_code, 302)
        uploader.refresh_from_db()
        self.assertTrue(uploader.is_active)
        self.assertTrue(uploader.is_uploader)

        share.is_enabled = True
        share.save(update_fields=["is_enabled"])
        disabled_shares = self.client.post(
            reverse("moderate_user", args=[uploader.pk, "disable_user_shares"])
        )
        self.assertEqual(disabled_shares.status_code, 302)
        share.refresh_from_db()
        self.assertFalse(share.is_enabled)

    def test_staff_can_browse_user_files_with_stats_and_share_links(self):
        uploader = self.make_uploader(username="librarycreator")
        staff = User.objects.create_user(
            username="librarystaff", password="pass", is_staff=True, is_uploader=True
        )
        root = Folder.get_root(uploader)
        folder = Folder.objects.create(owner=uploader, parent=root, name="Library")
        stored_file = self.make_available_file(uploader, folder, name="library.zip")
        stored_file.download_count = 3
        stored_file.save(update_fields=["download_count"])
        share = PublicShare.objects.create(
            owner=uploader,
            target_type=PublicShare.TargetType.FOLDER,
            folder=folder,
        )
        DownloadEvent.objects.create(
            stored_file=stored_file,
            share=share,
            ip_hash="ip",
            user_agent_hash="ua",
            bytes_served=stored_file.size,
            outcome=DownloadEvent.Outcome.ALLOWED,
        )
        self.client.force_login(staff)

        users = self.client.get(reverse("moderation_users"), {"q": "librarycreator"})
        self.assertEqual(users.status_code, 200)
        self.assertContains(users, reverse("moderation_user_files", args=[uploader.pk]))

        response = self.client.get(reverse("moderation_user_files", args=[uploader.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "librarycreator")
        self.assertContains(response, "/Library")
        self.assertContains(response, "library.zip")
        self.assertContains(response, "3 total")
        self.assertContains(response, "1 allowed events")
        self.assertContains(response, reverse("public_folder", args=[share.slug]))
        self.assertNotContains(response, f"/d/{share.slug}/f/{stored_file.pk}/")

    def test_staff_cannot_suspend_self(self):
        staff = User.objects.create_user(
            username="selfstaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.post(reverse("moderate_user", args=[staff.pk, "suspend_user"]))

        self.assertEqual(response.status_code, 403)
        staff.refresh_from_db()
        self.assertTrue(staff.is_active)

    def test_staff_can_set_and_clear_quota_override(self):
        uploader = self.make_uploader(username="quotacreator")
        staff = User.objects.create_user(
            username="quotastaff", password="pass", is_staff=True, is_uploader=True
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderation_user_quota", args=[uploader.pk]),
            {
                "storage_quota_gib": "2",
                "max_file_size_mib": "256",
                "max_file_count": "12",
                "folder_depth_limit": "6",
            },
        )

        self.assertEqual(response.status_code, 302)
        quota_override = QuotaOverride.objects.get(user=uploader)
        self.assertEqual(quota_override.storage_quota_bytes, 2 * 1024**3)
        self.assertEqual(quota_override.max_file_size_bytes, 256 * 1024**2)
        self.assertEqual(quota_override.max_file_count, 12)
        self.assertEqual(quota_override.folder_depth_limit, 6)
        quota = effective_quota(uploader)
        self.assertEqual(quota.storage_quota_bytes, 2 * 1024**3)
        self.assertEqual(quota.max_file_size_bytes, 256 * 1024**2)
        self.assertEqual(quota.max_file_count, 12)
        self.assertEqual(quota.folder_depth_limit, 6)
        self.assertTrue(
            ModerationAction.objects.filter(
                actor=staff,
                target_user=uploader,
                action=ModerationAction.Action.UPDATE_QUOTA,
                metadata__max_file_count=12,
            ).exists()
        )

        page = self.client.get(reverse("moderation_user_quota", args=[uploader.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "quotacreator")
        self.assertContains(page, "256")

        cleared = self.client.post(reverse("moderation_user_quota", args=[uploader.pk]), {})
        self.assertEqual(cleared.status_code, 302)
        self.assertFalse(QuotaOverride.objects.filter(user=uploader).exists())
        uploader.refresh_from_db()
        self.assertEqual(effective_quota(uploader).max_file_count, 10_000)

    def test_quota_override_takes_precedence_over_legacy_user_fields(self):
        uploader = self.make_uploader(username="legacyquota")
        uploader.max_file_count = 99
        uploader.save(update_fields=["max_file_count"])
        QuotaOverride.objects.create(user=uploader, max_file_count=7)

        self.assertEqual(effective_quota(uploader).max_file_count, 7)

    def test_check_operations_health_management_command_reports_status(self):
        output = StringIO()

        call_command("check_operations_health", stdout=output)

        text = output.getvalue()
        self.assertIn("Database", text)
        self.assertIn("Private storage", text)
        self.assertIn("Overall:", text)

    @override_settings(PARAFILES_ALLOW_SCAN_BYPASS=False)
    def test_check_operations_health_management_command_fails_on_errors(self):
        with self.assertRaises(CommandError):
            call_command("check_operations_health", stdout=StringIO())

    def test_reset_site_management_command_clears_database_only_by_default(self):
        user = self.make_uploader(username="resetuser")
        stored_file = self.make_available_file(user, Folder.get_root(user), name="reset.zip")
        file_path = private_path(stored_file.storage_key)
        output = StringIO()

        call_command("reset_site", "--noinput", stdout=output)

        self.assertFalse(User.objects.filter(username="resetuser").exists())
        self.assertFalse(StoredFile.objects.filter(pk=stored_file.pk).exists())
        self.assertTrue(file_path.exists())
        self.assertIn("File data will be left untouched.", output.getvalue())

    def test_reset_site_management_command_can_remove_file_data(self):
        user = self.make_uploader(username="resetfilesuser")
        self.make_available_file(user, Folder.get_root(user), name="reset-files.zip")
        output = StringIO()

        with patch(
            "fileshare.management.commands.reset_site.Command.clear_directory"
        ) as clear_directory:
            call_command("reset_site", "--noinput", "--remove-files", stdout=output)

        self.assertFalse(User.objects.filter(username="resetfilesuser").exists())
        self.assertEqual(
            [call_args.args[0] for call_args in clear_directory.call_args_list],
            [settings.PARAFILES_STORAGE_ROOT, settings.PARAFILES_UPLOAD_SESSION_ROOT],
        )
        self.assertIn("File data cleared:", output.getvalue())

    def test_staff_can_bulk_resolve_reports(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="bulkreportstaff", password="pass", is_staff=True, is_uploader=True
        )
        stored_file = self.make_available_file(uploader, Folder.get_root(uploader), name="bulk-report.zip")
        share = PublicShare.objects.create(
            owner=uploader, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        first = AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.OTHER,
            message="First report",
            reporter_ip_hash="ip1",
        )
        second = AbuseReport.objects.create(
            share=share,
            stored_file=stored_file,
            category=AbuseReport.Category.OTHER,
            message="Second report",
            reporter_ip_hash="ip2",
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderation_bulk_action"),
            {
                "target": "reports",
                "action": AbuseReport.Status.RESOLVED,
                "ids": [first.pk, second.pk],
                "reason": "Duplicate reports handled.",
            },
        )

        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, AbuseReport.Status.RESOLVED)
        self.assertEqual(second.status, AbuseReport.Status.RESOLVED)
        self.assertEqual(first.handled_by, staff)
        self.assertTrue(
            ModerationAction.objects.filter(
                actor=staff,
                report=first,
                action=ModerationAction.Action.RESOLVE_REPORT,
                reason="Duplicate reports handled.",
            ).exists()
        )

    def test_staff_can_bulk_quarantine_files(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="bulkfilestaff", password="pass", is_staff=True, is_uploader=True
        )
        root = Folder.get_root(uploader)
        first = self.make_available_file(uploader, root, name="bad-one.zip")
        second = self.make_available_file(uploader, root, name="bad-two.zip")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderation_bulk_action"),
            {
                "target": "files",
                "action": ModerationAction.Action.QUARANTINE,
                "ids": [first.pk, second.pk],
                "reason": "Known bad hash.",
            },
        )

        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, StoredFile.Status.QUARANTINED)
        self.assertEqual(second.status, StoredFile.Status.QUARANTINED)
        self.assertEqual(
            ModerationAction.objects.filter(
                actor=staff,
                action=ModerationAction.Action.QUARANTINE,
                reason="Known bad hash.",
            ).count(),
            2,
        )

    def test_staff_can_bulk_hide_folders_but_skips_root(self):
        uploader = self.make_uploader()
        staff = User.objects.create_user(
            username="bulkfolderstaff", password="pass", is_staff=True, is_uploader=True
        )
        root = Folder.get_root(uploader)
        folder = Folder.objects.create(owner=uploader, parent=root, name="Reported Folder")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("moderation_bulk_action"),
            {
                "target": "folders",
                "action": ModerationAction.Action.HIDE,
                "ids": [root.pk, folder.pk],
                "reason": "Folder report confirmed.",
            },
        )

        self.assertEqual(response.status_code, 302)
        root.refresh_from_db()
        folder.refresh_from_db()
        self.assertFalse(root.is_deleted)
        self.assertTrue(folder.is_deleted)
        self.assertTrue(
            ModerationAction.objects.filter(
                actor=staff,
                folder=folder,
                action=ModerationAction.Action.HIDE,
                reason="Folder report confirmed.",
            ).exists()
        )

    @override_settings(PARAFILES_PUBLIC_PAGE_VIEWS_PER_IP_PER_MINUTE=1)
    def test_public_page_rate_limit_blocks_repeated_views(self):
        cache.clear()
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )
        first = self.client.get(reverse("public_file", args=[share.slug]))
        second = self.client.get(reverse("public_file", args=[share.slug]))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_security_headers_are_present(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_health_check_reports_ok(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"]["database"], "ok")

    @override_settings(DEBUG=False)
    def test_custom_unavailable_page_renders_for_missing_public_link(self):
        response = self.client.get(reverse("public_file", args=["missing"]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Unavailable", status_code=404)

    @override_settings(PARAFILES_CONCURRENT_DOWNLOADS_PER_IP=1)
    def test_concurrent_download_limit_blocks_until_slot_released(self):
        cache.clear()
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user))
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )

        first = self.client.post(reverse("prepare_download", args=[share.slug]))
        second = self.client.post(reverse("prepare_download", args=[share.slug]))

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 429)

        download = self.client.get(first["Location"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), b"mod-data")

        third = self.client.post(reverse("prepare_download", args=[share.slug]))
        self.assertEqual(third.status_code, 302)

    @override_settings(PARAFILES_DAILY_IP_BANDWIDTH_BYTES=1, PARAFILES_SLOWDOWN_BYTES_PER_SECOND=1234)
    def test_bandwidth_slowdown_sets_nginx_limit_header(self):
        cache.clear()
        user = self.make_uploader()
        stored_file = self.make_available_file(user, Folder.get_root(user), body=b"large")
        share = PublicShare.objects.create(
            owner=user, target_type=PublicShare.TargetType.FILE, stored_file=stored_file
        )

        prepared = self.client.post(reverse("prepare_download", args=[share.slug]))
        response = self.client.get(prepared["Location"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Accel-Limit-Rate"], "1234")

    @override_settings(
        DEBUG=False,
        SECRET_KEY="native-test-secret-7b8a50d0a1dc4f0bbcf94cc0f278c58df745fcadf2d2477090",
        ALLOWED_HOSTS=["files.paralives.example"],
        REDIS_URL="redis://127.0.0.1:6379/0",
        PARAFILES_STORAGE_ROOT=Path("/srv/parafiles/private_uploads"),
        PARAFILES_UPLOAD_SESSION_ROOT=Path("/srv/parafiles/upload_sessions"),
        PARAFILES_SERVE_PRIVATE_DOWNLOADS=False,
        PARAFILES_ALLOW_SCAN_BYPASS=False,
        PARAFILES_ADMIN_2FA_REQUIRED=True,
        PARAFILES_SIGNATURE_PRIVATE_KEY=TEST_SIGNATURE_PRIVATE_KEY,
        PARAFILES_SIGNATURE_PUBLIC_KEY=TEST_SIGNATURE_PUBLIC_KEY,
        CSRF_TRUSTED_ORIGINS=["https://files.paralives.example"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    )
    def test_deploy_checks_accept_safe_native_config(self):
        databases = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "parafiles",
            }
        }
        with patch.object(settings, "DATABASES", databases):
            self.assertEqual(parafiles_deploy_checks(None), [])

    @override_settings(
        DEBUG=False,
        SECRET_KEY="dev-only-change-me",
        ALLOWED_HOSTS=["parafiles.example.com"],
        PARAFILES_SERVE_PRIVATE_DOWNLOADS=True,
        PARAFILES_ADMIN_2FA_REQUIRED=False,
        PARAFILES_SIGNATURE_PRIVATE_KEY="",
        PARAFILES_SIGNATURE_PUBLIC_KEY="",
        CSRF_TRUSTED_ORIGINS=[],
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    )
    def test_deploy_checks_flag_unsafe_native_config(self):
        issue_ids = {issue.id for issue in parafiles_deploy_checks(None)}
        self.assertSetEqual(
            issue_ids,
            {
                "parafiles.E001",
                "parafiles.E002",
                "parafiles.E003",
                "parafiles.E004",
                "parafiles.E005",
                "parafiles.E006",
                "parafiles.E007",
                "parafiles.E008",
                "parafiles.E010",
                "parafiles.W001",
                "parafiles.W002",
                "parafiles.W003",
                "parafiles.W004",
            },
        )

    @override_settings(
        DEBUG=False,
        SECRET_KEY="native-test-secret-7b8a50d0a1dc4f0bbcf94cc0f278c58df745fcadf2d2477090",
        ALLOWED_HOSTS=["files.paralives.example"],
        REDIS_URL="redis://127.0.0.1:6379/0",
        PARAFILES_STORAGE_ROOT=Path("/srv/parafiles/private_uploads"),
        PARAFILES_UPLOAD_SESSION_ROOT=Path("/srv/parafiles/upload_sessions"),
        PARAFILES_SERVE_PRIVATE_DOWNLOADS=False,
        PARAFILES_ALLOW_SCAN_BYPASS=False,
        PARAFILES_ADMIN_2FA_REQUIRED=True,
        PARAFILES_SIGNATURE_PRIVATE_KEY=TEST_SIGNATURE_PRIVATE_KEY,
        PARAFILES_SIGNATURE_PUBLIC_KEY=base64.b64encode(b"x" * 32).decode("ascii"),
        CSRF_TRUSTED_ORIGINS=["https://files.paralives.example"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    )
    def test_deploy_checks_reject_mismatched_signature_keypair(self):
        databases = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "parafiles",
            }
        }
        with patch.object(settings, "DATABASES", databases):
            issue_ids = {issue.id for issue in parafiles_deploy_checks(None)}
        self.assertEqual(issue_ids, {"parafiles.E009"})
