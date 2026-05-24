from __future__ import annotations

import subprocess
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from fileshare.models import ScanResult, StoredFile
from fileshare.services.storage import private_path


def create_result(
    stored_file: StoredFile,
    engine: str,
    status: str,
    signature: str = "",
    raw_result: dict[str, Any] | None = None,
) -> ScanResult:
    return ScanResult.objects.create(
        stored_file=stored_file,
        engine=engine,
        status=status,
        signature=signature,
        raw_result=raw_result or {},
    )


def scan_with_clamav(stored_file: StoredFile) -> ScanResult:
    command = settings.PARAFILES_CLAMAV_COMMAND
    path = private_path(stored_file.storage_key)
    try:
        completed = subprocess.run(
            [command, "--no-summary", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        if settings.PARAFILES_ALLOW_SCAN_BYPASS:
            return create_result(
                stored_file,
                ScanResult.Engine.CLAMAV,
                ScanResult.Status.SKIPPED,
                "scanner unavailable",
                {"error": str(exc)},
            )
        return create_result(
            stored_file,
            ScanResult.Engine.CLAMAV,
            ScanResult.Status.ERROR,
            "scanner unavailable",
            {"error": str(exc)},
        )

    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode == 0:
        return create_result(
            stored_file, ScanResult.Engine.CLAMAV, ScanResult.Status.CLEAN, raw_result={"output": output}
        )
    if completed.returncode == 1:
        return create_result(
            stored_file,
            ScanResult.Engine.CLAMAV,
            ScanResult.Status.MALICIOUS,
            output[:255],
            {"output": output},
        )
    return create_result(
        stored_file,
        ScanResult.Engine.CLAMAV,
        ScanResult.Status.ERROR,
        output[:255],
        {"output": output, "returncode": completed.returncode},
    )


def check_virustotal_hash(stored_file: StoredFile) -> ScanResult | None:
    api_key = settings.VIRUSTOTAL_API_KEY
    if not api_key:
        return None
    response = requests.get(
        f"https://www.virustotal.com/api/v3/files/{stored_file.sha256}",
        headers={"x-apikey": api_key},
        timeout=15,
    )
    if response.status_code == 404:
        return create_result(
            stored_file,
            ScanResult.Engine.VIRUSTOTAL_HASH,
            ScanResult.Status.SKIPPED,
            "hash not found",
            {"status_code": 404},
        )
    if response.status_code >= 400:
        return create_result(
            stored_file,
            ScanResult.Engine.VIRUSTOTAL_HASH,
            ScanResult.Status.ERROR,
            f"HTTP {response.status_code}",
            {"body": response.text[:1000]},
        )

    payload = response.json()
    stats = payload.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
    malicious = int(stats.get("malicious") or 0)
    suspicious = int(stats.get("suspicious") or 0)
    if malicious > 0:
        status = ScanResult.Status.MALICIOUS
    elif suspicious > 0:
        status = ScanResult.Status.SUSPICIOUS
    else:
        status = ScanResult.Status.CLEAN
    return create_result(
        stored_file,
        ScanResult.Engine.VIRUSTOTAL_HASH,
        status,
        f"malicious={malicious}, suspicious={suspicious}",
        payload,
    )


def run_scan_for_file(stored_file_id: int) -> None:
    stored_file = StoredFile.objects.get(pk=stored_file_id)
    stored_file.status = StoredFile.Status.SCANNING
    stored_file.save(update_fields=["status", "updated_at"])

    clamav = scan_with_clamav(stored_file)
    vt = check_virustotal_hash(stored_file)
    results = [result for result in [clamav, vt] if result is not None]

    if any(result.status == ScanResult.Status.MALICIOUS for result in results):
        stored_file.status = StoredFile.Status.QUARANTINED
    elif any(result.status in {ScanResult.Status.SUSPICIOUS, ScanResult.Status.ERROR} for result in results):
        stored_file.status = StoredFile.Status.REVIEW
    else:
        stored_file.status = StoredFile.Status.AVAILABLE
    stored_file.scan_completed_at = timezone.now()
    stored_file.save(update_fields=["status", "scan_completed_at", "updated_at"])
