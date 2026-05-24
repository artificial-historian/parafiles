from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

from fileshare.models import RateLimitEvent
from fileshare.services.security import request_ip_hash, request_user_agent_hash


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    slowed: bool = False
    retry_after: int = 0
    limit_rate: int = 0
    concurrency_key: str = ""


def increment_window(scope: str, identity: str, limit: int, seconds: int) -> tuple[bool, int]:
    key = f"rl:{scope}:{identity}"
    added = cache.add(key, 0, seconds)
    count = cache.incr(key)
    if added:
        cache.touch(key, seconds)
    return count <= limit, count


def check_public_page(request: HttpRequest) -> ThrottleDecision:
    ip_hash = request_ip_hash(request)
    allowed, count = increment_window(
        "public-page", ip_hash, settings.PARAFILES_PUBLIC_PAGE_VIEWS_PER_IP_PER_MINUTE, 60
    )
    if not allowed:
        RateLimitEvent.objects.create(
            scope="public-page",
            key=ip_hash,
            ip_hash=ip_hash,
            user_agent_hash=request_user_agent_hash(request),
            count=count,
            action=RateLimitEvent.Action.BLOCK,
        )
        return ThrottleDecision(False, retry_after=60)
    return ThrottleDecision(True)


def check_report(request: HttpRequest) -> ThrottleDecision:
    ip_hash = request_ip_hash(request)
    allowed, count = increment_window(
        "report", ip_hash, settings.PARAFILES_REPORTS_PER_IP_PER_HOUR, 3600
    )
    if not allowed:
        RateLimitEvent.objects.create(
            scope="report",
            key=ip_hash,
            ip_hash=ip_hash,
            user_agent_hash=request_user_agent_hash(request),
            count=count,
            action=RateLimitEvent.Action.BLOCK,
        )
        return ThrottleDecision(False, retry_after=3600)
    return ThrottleDecision(True)


def check_download_request(request: HttpRequest, size: int) -> ThrottleDecision:
    ip_hash = request_ip_hash(request)
    concurrent_key = f"rl:download-concurrent:{ip_hash}"
    cache.add(concurrent_key, 0, settings.PARAFILES_CONCURRENT_DOWNLOAD_WINDOW_SECONDS)
    concurrent_count = cache.incr(concurrent_key)
    cache.touch(concurrent_key, settings.PARAFILES_CONCURRENT_DOWNLOAD_WINDOW_SECONDS)
    if concurrent_count > settings.PARAFILES_CONCURRENT_DOWNLOADS_PER_IP:
        cache.decr(concurrent_key)
        RateLimitEvent.objects.create(
            scope="download-concurrent",
            key=ip_hash,
            ip_hash=ip_hash,
            user_agent_hash=request_user_agent_hash(request),
            count=concurrent_count,
            action=RateLimitEvent.Action.BLOCK,
        )
        return ThrottleDecision(
            False,
            retry_after=settings.PARAFILES_CONCURRENT_DOWNLOAD_WINDOW_SECONDS,
        )

    minute_allowed, minute_count = increment_window(
        "download-minute", ip_hash, settings.PARAFILES_DOWNLOADS_PER_IP_PER_MINUTE, 60
    )
    if not minute_allowed:
        release_download_slot(concurrent_key)
        RateLimitEvent.objects.create(
            scope="download-minute",
            key=ip_hash,
            ip_hash=ip_hash,
            user_agent_hash=request_user_agent_hash(request),
            count=minute_count,
            action=RateLimitEvent.Action.BLOCK,
        )
        return ThrottleDecision(False, retry_after=60)

    day_key = f"rl:download-bytes:{ip_hash}"
    cache.add(day_key, 0, 86400)
    total = cache.incr(day_key, size)
    cache.touch(day_key, 86400)
    if total > settings.PARAFILES_DAILY_IP_BANDWIDTH_BYTES:
        RateLimitEvent.objects.create(
            scope="download-bytes",
            key=ip_hash,
            ip_hash=ip_hash,
            user_agent_hash=request_user_agent_hash(request),
            count=total,
            action=RateLimitEvent.Action.SLOW,
        )
        return ThrottleDecision(
            True,
            slowed=True,
            limit_rate=settings.PARAFILES_SLOWDOWN_BYTES_PER_SECOND,
            concurrency_key=concurrent_key,
        )
    return ThrottleDecision(True, concurrency_key=concurrent_key)


def release_download_slot(concurrency_key: str) -> None:
    if not concurrency_key:
        return
    try:
        current = cache.get(concurrency_key)
        if current is None or int(current) <= 0:
            cache.set(concurrency_key, 0, settings.PARAFILES_CONCURRENT_DOWNLOAD_WINDOW_SECONDS)
        else:
            cache.decr(concurrency_key)
    except Exception:
        pass
