from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "fileshare.apps.FileshareConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "fileshare.middleware.StaffTwoFactorRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "fileshare.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "parafiles_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "parafiles_project.wsgi.application"


def database_from_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or "",
        }
    if parsed.scheme == "sqlite":
        path = parsed.path
        if os.name == "nt" and path.startswith("/") and len(path) > 3 and path[2] == ":":
            path = path[1:]
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": path}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


DATABASE_URL = os.environ.get("DATABASE_URL")
DEFAULT_SQLITE_PATH = BASE_DIR / "var" / "db.sqlite3"
DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASES = {
    "default": database_from_url(DATABASE_URL)
    if DATABASE_URL
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": DEFAULT_SQLITE_PATH}
}

REDIS_URL = os.environ.get("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = os.environ.get("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "fileshare.User"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@parafiles.local")
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 25)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 10)

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

PARAFILES_STORAGE_ROOT = Path(
    os.environ.get("PARAFILES_STORAGE_ROOT", BASE_DIR / "var" / "private_uploads")
)
PARAFILES_SITE_NAME = os.environ.get("PARAFILES_SITE_NAME", "Parafiles")
PARAFILES_UPLOAD_SESSION_ROOT = Path(
    os.environ.get("PARAFILES_UPLOAD_SESSION_ROOT", BASE_DIR / "var" / "upload_sessions")
)
PARAFILES_INTERNAL_DOWNLOAD_PREFIX = os.environ.get(
    "PARAFILES_INTERNAL_DOWNLOAD_PREFIX", "/protected-files/"
)
PARAFILES_SERVE_PRIVATE_DOWNLOADS = env_bool("PARAFILES_SERVE_PRIVATE_DOWNLOADS", DEBUG)
PARAFILES_SCAN_SYNC = env_bool("PARAFILES_SCAN_SYNC", DEBUG)
PARAFILES_ALLOW_SCAN_BYPASS = env_bool("PARAFILES_ALLOW_SCAN_BYPASS", DEBUG)
PARAFILES_CLAMAV_COMMAND = os.environ.get("PARAFILES_CLAMAV_COMMAND", "clamscan")
PARAFILES_ADMIN_2FA_REQUIRED = env_bool("PARAFILES_ADMIN_2FA_REQUIRED", not DEBUG)
OTP_TOTP_ISSUER = os.environ.get("OTP_TOTP_ISSUER", "Parafiles")

PARAFILES_DEFAULT_QUOTA_BYTES = env_int("PARAFILES_DEFAULT_QUOTA_BYTES", 10 * 1024**3)
PARAFILES_DEFAULT_MAX_FILE_SIZE_BYTES = env_int(
    "PARAFILES_DEFAULT_MAX_FILE_SIZE_BYTES", 1024**3
)
PARAFILES_DEFAULT_MAX_FILE_COUNT = env_int("PARAFILES_DEFAULT_MAX_FILE_COUNT", 10_000)
PARAFILES_DEFAULT_MAX_FOLDER_DEPTH = env_int("PARAFILES_DEFAULT_MAX_FOLDER_DEPTH", 20)
PARAFILES_UPLOAD_SESSION_TTL_SECONDS = env_int("PARAFILES_UPLOAD_SESSION_TTL_SECONDS", 86400)
PARAFILES_UPLOAD_STAGING_RETENTION_SECONDS = env_int(
    "PARAFILES_UPLOAD_STAGING_RETENTION_SECONDS", 7 * 86400
)
PARAFILES_DOWNLOAD_TOKEN_TTL_SECONDS = env_int("PARAFILES_DOWNLOAD_TOKEN_TTL_SECONDS", 90)
PARAFILES_CONCURRENT_DOWNLOADS_PER_IP = env_int("PARAFILES_CONCURRENT_DOWNLOADS_PER_IP", 4)
PARAFILES_CONCURRENT_DOWNLOAD_WINDOW_SECONDS = env_int(
    "PARAFILES_CONCURRENT_DOWNLOAD_WINDOW_SECONDS", 300
)
PARAFILES_DAILY_IP_BANDWIDTH_BYTES = env_int(
    "PARAFILES_DAILY_IP_BANDWIDTH_BYTES", 5 * 1024**3
)
PARAFILES_REPORTS_PER_IP_PER_HOUR = env_int("PARAFILES_REPORTS_PER_IP_PER_HOUR", 5)
PARAFILES_DOWNLOADS_PER_IP_PER_MINUTE = env_int("PARAFILES_DOWNLOADS_PER_IP_PER_MINUTE", 30)
PARAFILES_PUBLIC_PAGE_VIEWS_PER_IP_PER_MINUTE = env_int(
    "PARAFILES_PUBLIC_PAGE_VIEWS_PER_IP_PER_MINUTE", 120
)
PARAFILES_SLOWDOWN_BYTES_PER_SECOND = env_int("PARAFILES_SLOWDOWN_BYTES_PER_SECOND", 128 * 1024)
PARAFILES_CONTENT_SECURITY_POLICY = os.environ.get(
    "PARAFILES_CONTENT_SECURITY_POLICY",
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'",
)

VIRUSTOTAL_API_KEY = os.environ.get("VIRUSTOTAL_API_KEY", "")
VIRUSTOTAL_SUBMIT_FILES = env_bool("VIRUSTOTAL_SUBMIT_FILES", False)

CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("DJANGO_USE_X_FORWARDED_HOST", False)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
