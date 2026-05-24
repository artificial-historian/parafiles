from celery import shared_task

from fileshare.services.cleanup import cleanup_expired_uploads
from fileshare.services.scanning import run_scan_for_file


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def scan_file_task(self, stored_file_id: int) -> None:
    run_scan_for_file(stored_file_id)


@shared_task
def cleanup_expired_uploads_task() -> dict:
    result = cleanup_expired_uploads()
    return {
        "expired_sessions": result.expired_sessions,
        "temp_files_deleted": result.temp_files_deleted,
        "orphan_temp_files_deleted": result.orphan_temp_files_deleted,
        "bytes_deleted": result.bytes_deleted,
    }
