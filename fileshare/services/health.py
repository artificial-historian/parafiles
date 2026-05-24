from __future__ import annotations

import shlex
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connection


@dataclass
class HealthCheck:
    name: str
    status: str
    detail: str


def check_database() -> HealthCheck:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return HealthCheck("Database", "error", exc.__class__.__name__)
    return HealthCheck("Database", "ok", connection.vendor)


def check_cache() -> HealthCheck:
    key = f"operations-health:{uuid.uuid4().hex}"
    try:
        cache.set(key, "ok", 5)
        value = cache.get(key)
        cache.delete(key)
    except Exception as exc:
        return HealthCheck("Cache", "error", exc.__class__.__name__)
    if value != "ok":
        return HealthCheck("Cache", "error", "cache read/write mismatch")
    backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]
    return HealthCheck("Cache", "ok", backend)


def check_writable_directory(name: str, path: Path) -> HealthCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".health-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "ok":
            return HealthCheck(name, "error", "write/read mismatch")
    except Exception as exc:
        return HealthCheck(name, "error", f"{path}: {exc.__class__.__name__}")
    try:
        probe.unlink()
    except Exception as exc:
        return HealthCheck(name, "warn", f"{path}: probe cleanup failed: {exc.__class__.__name__}")
    return HealthCheck(name, "ok", str(path))


def check_clamav() -> HealthCheck:
    command = settings.PARAFILES_CLAMAV_COMMAND
    try:
        executable = shlex.split(command)[0]
    except ValueError:
        executable = command
    found = shutil.which(executable)
    if found:
        return HealthCheck("ClamAV", "ok", found)
    status = "warn" if settings.PARAFILES_ALLOW_SCAN_BYPASS else "error"
    return HealthCheck("ClamAV", status, f"{executable} not found")


def check_virustotal() -> HealthCheck:
    if not settings.VIRUSTOTAL_API_KEY:
        return HealthCheck("VirusTotal", "warn", "hash lookup not configured")
    if settings.VIRUSTOTAL_SUBMIT_FILES:
        return HealthCheck("VirusTotal", "warn", "full file submission is enabled")
    return HealthCheck("VirusTotal", "ok", "hash lookup configured")


def check_download_serving() -> HealthCheck:
    if settings.PARAFILES_SERVE_PRIVATE_DOWNLOADS:
        return HealthCheck("Protected downloads", "warn", "Django serves private files directly")
    return HealthCheck(
        "Protected downloads",
        "ok",
        f"X-Accel-Redirect via {settings.PARAFILES_INTERNAL_DOWNLOAD_PREFIX}",
    )


def check_worker_backend() -> HealthCheck:
    broker = settings.CELERY_BROKER_URL
    if broker == "memory://":
        return HealthCheck("Celery broker", "warn", "memory broker configured")
    return HealthCheck("Celery broker", "ok", broker.split("://", 1)[0])


def operations_health() -> tuple[str, list[HealthCheck]]:
    checks = [
        check_database(),
        check_cache(),
        check_writable_directory("Private storage", settings.PARAFILES_STORAGE_ROOT),
        check_writable_directory("Upload staging", settings.PARAFILES_UPLOAD_SESSION_ROOT),
        check_clamav(),
        check_virustotal(),
        check_download_serving(),
        check_worker_backend(),
    ]
    if any(check.status == "error" for check in checks):
        return "error", checks
    if any(check.status == "warn" for check in checks):
        return "warn", checks
    return "ok", checks
