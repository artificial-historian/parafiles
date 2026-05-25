from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.urls import reverse

from fileshare.models import User


TOKEN_SALT = "fileshare.email-verification"
TOKEN_PURPOSE = "email-verification"


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def verified_email_is_taken(email: str, user: User) -> bool:
    normalized = normalize_email(email)
    if not normalized:
        return False
    return (
        User.objects.filter(verified_email__iexact=normalized)
        .exclude(pk=user.pk)
        .exists()
    )


def email_verification_token(user: User, email: str) -> str:
    normalized = normalize_email(email)
    return signing.dumps(
        {"purpose": TOKEN_PURPOSE, "user_id": user.pk, "email": normalized},
        salt=TOKEN_SALT,
    )


def unpack_email_verification_token(token: str) -> tuple[int, str]:
    try:
        payload = signing.loads(
            token,
            salt=TOKEN_SALT,
            max_age=settings.PARAFILES_EMAIL_VERIFICATION_TIMEOUT,
        )
    except signing.BadSignature as exc:
        raise ValidationError("Invalid or expired email verification link.") from exc

    if payload.get("purpose") != TOKEN_PURPOSE:
        raise ValidationError("Invalid email verification link.")
    try:
        user_id = int(payload["user_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Invalid email verification link.") from exc

    email = normalize_email(payload.get("email"))
    if not email:
        raise ValidationError("Invalid email verification link.")
    return user_id, email


def email_verification_url(request, user: User, email: str) -> str:
    token = email_verification_token(user, email)
    return request.build_absolute_uri(reverse("verify_email", args=[token]))


def email_verification_body(user: User, url: str) -> str:
    expiry_hours = settings.PARAFILES_EMAIL_VERIFICATION_TIMEOUT // 3600
    return (
        f"Verify this email address for your {settings.PARAFILES_SITE_NAME} account.\n\n"
        f"Use this verification link:\n{url}\n\n"
        f"The link expires in {expiry_hours} hours.\n"
        "If you did not request this change, you can ignore this email.\n"
    )


def send_email_verification(request, user: User, email: str) -> int:
    normalized = normalize_email(email)
    if not normalized:
        return 0
    url = email_verification_url(request, user, normalized)
    subject = f"Verify your {settings.PARAFILES_SITE_NAME} email address"
    return send_mail(
        subject,
        email_verification_body(user, url),
        settings.DEFAULT_FROM_EMAIL,
        [normalized],
        fail_silently=False,
    )
