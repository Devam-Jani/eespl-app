"""A small in-process rate limit for the public receipt link (no login there): at most N
requests per client address in a sliding window. One API process runs the app today; at go-live
behind a proxy, the proxy's limit applies as well."""

import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

_hits: dict[str, deque] = {}
_lock = threading.Lock()


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown"))[
        :64
    ]


def check(request: Request, bucket: str, limit: int, window_s: int) -> None:
    key = f"{bucket}:{client_key(request)}"
    t = time.monotonic()
    with _lock:
        q = _hits.setdefault(key, deque())
        while q and t - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many tries: wait a few minutes and try again",
            )
        q.append(t)


def reset() -> None:
    with _lock:
        _hits.clear()
