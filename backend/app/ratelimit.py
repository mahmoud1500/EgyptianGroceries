"""Tiny in-memory sliding-window rate limiter for abuse-prone endpoints.

Protects login/register/forgot-password/reset/change-password against
credential stuffing and email bombing. No external dependencies.

Notes/limits of this approach (see README production checklist):
- Buckets live in process memory: with multiple uvicorn workers each worker
  enforces its own counters. For production behind a proxy/CDN, enforce
  rate limiting at the edge as well.
- Keys are the direct TCP peer IP (request.client.host). X-Forwarded-For is
  deliberately NOT trusted here because it is client-spoofable.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# scope:ip -> deque of monotonic timestamps of recent hits
_buckets: dict[str, deque[float]] = defaultdict(deque)
_MAX_BUCKETS = 20000  # safety cap on distinct keys held in memory


def client_ip(request: Request) -> str:
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def check_rate_limit(request: Request, scope: str, limit: int, window_seconds: int) -> None:
    """Allow `limit` hits per `window_seconds` for this scope+IP. Raises 429."""
    key = f"{scope}:{client_ip(request)}"
    now = time.monotonic()
    bucket = _buckets[key]
    cutoff = now - window_seconds
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts — please wait a bit and try again.",
            headers={"Retry-After": str(window_seconds)},
        )
    bucket.append(now)
    if len(_buckets) > _MAX_BUCKETS:
        # Memory safety valve: drop all counters (fail open, briefly).
        _buckets.clear()
