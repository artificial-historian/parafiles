from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Warning, register


PLACEHOLDER_SECRET_KEYS = {
    "dev-only-change-me",
    "change-me",
    "replace-with-long-random-secret",
}
PLACEHOLDER_HOSTS = {
    "localhost",
    "127.0.0.1",
    "[::1]",
    "parafiles.example.com",
    "test-parafiles.example.com",
}


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_parent = parent.resolve()
    except OSError:
        return False
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


@register(deploy=True)
def parafiles_deploy_checks(app_configs, **kwargs):
    issues = []
    if not settings.DEBUG and settings.SECRET_KEY in PLACEHOLDER_SECRET_KEYS:
        issues.append(
            Error(
                "DJANGO_SECRET_KEY must be changed when DEBUG is disabled.",
                id="parafiles.E001",
            )
        )
    if not settings.DEBUG and settings.PARAFILES_SERVE_PRIVATE_DOWNLOADS:
        issues.append(
            Error(
                "PARAFILES_SERVE_PRIVATE_DOWNLOADS must be false behind Nginx for deployment.",
                id="parafiles.E002",
            )
        )
    if not settings.DEBUG and not settings.PARAFILES_ADMIN_2FA_REQUIRED:
        issues.append(
            Error(
                "PARAFILES_ADMIN_2FA_REQUIRED must stay enabled for staff/admin accounts.",
                id="parafiles.E003",
            )
        )
    if not settings.DEBUG and (
        not settings.ALLOWED_HOSTS
        or "*" in settings.ALLOWED_HOSTS
        or all(host in PLACEHOLDER_HOSTS for host in settings.ALLOWED_HOSTS)
    ):
        issues.append(
            Error(
                "DJANGO_ALLOWED_HOSTS must name the real public host; do not deploy with "
                "wildcard, local-only, or example hosts.",
                id="parafiles.E004",
            )
        )
    default_database = settings.DATABASES.get("default", {})
    if not settings.DEBUG and str(default_database.get("ENGINE", "")).endswith("sqlite3"):
        issues.append(
            Error(
                "DATABASE_URL must point to PostgreSQL for native deployment.",
                id="parafiles.E005",
            )
        )
    if not settings.DEBUG and not getattr(settings, "REDIS_URL", ""):
        issues.append(
            Error(
                "REDIS_URL is required for native deployment throttles, download tokens, "
                "cache, and Celery.",
                id="parafiles.E006",
            )
        )
    if not settings.DEBUG and settings.PARAFILES_ALLOW_SCAN_BYPASS:
        issues.append(
            Error(
                "PARAFILES_ALLOW_SCAN_BYPASS must be false for native deployment.",
                id="parafiles.E007",
            )
        )
    if not settings.DEBUG and not settings.CSRF_TRUSTED_ORIGINS:
        issues.append(
            Warning(
                "Set DJANGO_CSRF_TRUSTED_ORIGINS to the public origin.",
                id="parafiles.W001",
            )
        )
    if not settings.DEBUG and settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        issues.append(
            Warning(
                "Configure SMTP email before relying on emailed invitations.",
                id="parafiles.W002",
            )
        )
    if not settings.DEBUG and path_is_inside(settings.PARAFILES_STORAGE_ROOT, settings.BASE_DIR):
        issues.append(
            Warning(
                "PARAFILES_STORAGE_ROOT should be outside the application source tree.",
                id="parafiles.W003",
            )
        )
    if not settings.DEBUG and path_is_inside(
        settings.PARAFILES_UPLOAD_SESSION_ROOT, settings.BASE_DIR
    ):
        issues.append(
            Warning(
                "PARAFILES_UPLOAD_SESSION_ROOT should be outside the application source tree.",
                id="parafiles.W004",
            )
        )
    return issues
