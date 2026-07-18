from __future__ import annotations

"""Rate limiter — in-memory by default, Redis when REDIS_URL is set.

Process-local dict is fine for UVICORN_WORKERS=1. When REDIS_URL is configured,
limits are shared across workers/instances via a fixed-window counter.

Trust X-Forwarded-For only when TRUST_PROXY=true.
"""

import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, DefaultDict, Deque, Optional

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger("sterling_syndicate.rate_limit")

_lock = Lock()
_hits: DefaultDict[str, Deque[float]] = defaultdict(deque)
_redis_client: Any = None
_redis_failed = False

_MAX_WINDOW_SECONDS = 3600
_GC_INTERVAL_SECONDS = 60
_last_gc: float = 0.0


def _gc_locked(now: float) -> None:
    global _last_gc
    if now - _last_gc < _GC_INTERVAL_SECONDS:
        return
    _last_gc = now
    cutoff = now - _MAX_WINDOW_SECONDS
    stale = [k for k, q in _hits.items() if not q or q[-1] < cutoff]
    for k in stale:
        del _hits[k]


def _get_redis() -> Optional[Any]:
    global _redis_client, _redis_failed
    if _redis_failed:
        return None
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # optional

        client = redis.Redis.from_url(url, decode_responses=True)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:  # noqa: BLE001
        _redis_failed = True
        logger.warning("Redis rate-limit unavailable, using memory: %s", exc)
        return None


def _rate_limit_memory(key: str, *, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        _gc_locked(now)
        q = _hits[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again shortly.",
            )
        q.append(now)


def rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    r = _get_redis()
    if r is not None:
        rk = f"rl:{key}"
        try:
            count = int(r.incr(rk))
            if count == 1:
                r.expire(rk, max(1, int(window_seconds)))
            if count > limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Try again shortly.",
                )
            return
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis rate-limit error, using memory: %s", exc)

    _rate_limit_memory(key, limit=limit, window_seconds=window_seconds)


def resolve_client_ip(request: Request) -> str:
    if settings.trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def client_key(request: Request, suffix: str, user_id: str = "") -> str:
    return f"{suffix}:{user_id or resolve_client_ip(request)}"


def reset_state() -> None:
    """Test helper: clear all buckets and GC bookkeeping."""
    global _last_gc, _redis_client, _redis_failed
    with _lock:
        _hits.clear()
        _last_gc = 0.0
    _redis_client = None
    _redis_failed = False
