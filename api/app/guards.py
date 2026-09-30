"""Hardening for the public, unauthenticated endpoints (spec 9.3).

Nothing here looks at or stores an IP address or user agent.
"""

import json
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError


async def read_limited(request: Request, limit: int) -> bytes:
    """Read the raw body, refusing more than `limit` bytes without buffering the excess."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="payload too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


M = TypeVar("M", bound=BaseModel)


def parse_model(body: bytes, model: type[M]) -> M:
    """Parse the raw body as JSON whatever the content type (sendBeacon sends text/plain),
    then validate. Any failure is a 422 that never echoes the submitted data."""
    try:
        data: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="body is not valid JSON") from None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        errors = [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors(include_input=False)]
        raise HTTPException(status_code=422, detail=errors) from None


class RateLimiter:
    """Sliding-window limiter per key, in memory (per process; see NOTES.md A47)."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = per_minute
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = self.clock()
        q = self.hits[key]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= self.limit:
            retry = max(1, int(60 - (now - q[0])) + 1)
            raise HTTPException(
                status_code=429, detail="rate limit exceeded", headers={"Retry-After": str(retry)}
            )
        q.append(now)


def require_origin(request: Request, allowed: list[str]) -> str:
    """The Origin header must be one of the shop's allowed origins. Browsers always send it on
    cross-origin POSTs, so a missing Origin means a non-browser client and is refused."""
    origin = request.headers.get("origin")
    if origin is None or origin not in allowed:
        raise HTTPException(status_code=403, detail="origin not allowed")
    return origin


def cors_headers(origin: str | None, allowed: list[str]) -> dict[str, str]:
    """CORS per shop, never `*`: the header is only sent for that shop's own origins."""
    if origin is not None and origin in allowed:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {"Vary": "Origin"}
