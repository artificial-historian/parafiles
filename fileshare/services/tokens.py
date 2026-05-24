from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, SuspiciousOperation

from fileshare.models import PublicShare, StoredFile

SALT = "parafiles.download-token"


def create_download_token(
    stored_file: StoredFile,
    share: PublicShare,
    ip_hash: str,
    user_agent_hash: str,
    *,
    concurrency_key: str = "",
    slowed: bool = False,
    limit_rate: int = 0,
) -> str:
    return signing.dumps(
        {
            "file_id": stored_file.pk,
            "share_id": share.pk,
            "ip": ip_hash,
            "ua": user_agent_hash,
            "ck": concurrency_key,
            "slow": slowed,
            "rate": limit_rate,
        },
        salt=SALT,
        compress=True,
    )


def load_download_token(
    token: str, ip_hash: str, user_agent_hash: str
) -> tuple[StoredFile, PublicShare, dict]:
    try:
        payload = signing.loads(
            token, salt=SALT, max_age=settings.PARAFILES_DOWNLOAD_TOKEN_TTL_SECONDS
        )
    except signing.BadSignature as exc:
        raise SuspiciousOperation("Invalid or expired download token.") from exc
    if payload.get("ip") != ip_hash or payload.get("ua") != user_agent_hash:
        raise PermissionDenied("Download token cannot be reused from this client.")
    stored_file = StoredFile.objects.select_related("owner", "folder").get(pk=payload["file_id"])
    share = PublicShare.objects.get(pk=payload["share_id"])
    return stored_file, share, payload
