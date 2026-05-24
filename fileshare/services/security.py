from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest

FILENAME_RE = re.compile(r"[^A-Za-z0-9._() -]+")


def client_ip(request: HttpRequest) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def user_agent(request: HttpRequest) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:512]


def keyed_hash(value: str) -> str:
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def request_ip_hash(request: HttpRequest) -> str:
    return keyed_hash(client_ip(request))


def request_user_agent_hash(request: HttpRequest) -> str:
    return keyed_hash(user_agent(request))


def sanitize_filename(filename: str) -> str:
    name = filename.split("/")[-1].split("\\")[-1].strip().strip(".")
    name = FILENAME_RE.sub("_", name)
    return name[:255] or "download"


def content_disposition(filename: str) -> str:
    safe = sanitize_filename(filename)
    quoted = quote(safe)
    ascii_fallback = safe.encode("ascii", "ignore").decode("ascii") or "download"
    ascii_fallback = ascii_fallback.replace("\\", "\\\\").replace('"', r"\"")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted}'
