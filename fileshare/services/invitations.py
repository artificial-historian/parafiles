from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from fileshare.models import Invitation


def invitation_url(request, invitation: Invitation) -> str:
    return request.build_absolute_uri(reverse("register_invite", args=[invitation.token]))


def invitation_email_body(invitation: Invitation, url: str) -> str:
    expires = invitation.expires_at.strftime("%Y-%m-%d %H:%M %Z")
    return (
        f"You have been invited to create a {settings.PARAFILES_SITE_NAME} uploader account.\n\n"
        f"Use this single-use invitation link:\n{url}\n\n"
        f"The invitation expires at {expires}.\n"
        "If you did not expect this invitation, you can ignore this email.\n"
    )


def send_invitation_email(invitation: Invitation, url: str) -> int:
    if not invitation.email:
        return 0
    subject = f"Your {settings.PARAFILES_SITE_NAME} uploader invitation"
    return send_mail(
        subject,
        invitation_email_body(invitation, url),
        settings.DEFAULT_FROM_EMAIL,
        [invitation.email],
        fail_silently=False,
    )
