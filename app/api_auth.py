"""Who may talk to this API, and how often (#824).

The API listens on every interface and, until now, answered anything that
could reach the port:

```
com.docke *:8000     API, every interface
com.docke *:5432     Postgres, every interface
```

That includes `POST /brain/ask`, which spends local model inference per call.
On a shared network it is an open compute endpoint.

## Why a shared secret and not accounts

The system serves one operator. An account model would be building for a user
who does not exist, and every extra moving part in an auth path is somewhere
for a mistake to hide. A token in `.env`, checked in one dependency, is the
smallest thing that is honestly sufficient.

## Why absent means open

Requiring a token by default would break a working development stack on
upgrade and teach whoever hit it to disable the check. Absent means open,
exactly as today — and the startup log says so, every time, because a
security property nobody can see is one nobody maintains.

## Why the probe is exempt

A liveness check that needs a credential cannot tell "down" from
"misconfigured", which is the one job it has.
"""

from __future__ import annotations

import hmac
import logging
import time
from collections import deque
from typing import Final

from fastapi import HTTPException, Request

from app.settings import settings

logger = logging.getLogger(__name__)

#: Endpoints answerable without a credential. Liveness only: everything else,
#: including read paths, is a statement about the operator's data.
PUBLIC_PATHS: Final[frozenset[str]] = frozenset({"/health"})

#: The one endpoint a browser cannot authenticate with a header.
STREAM_PATH: Final[str] = "/stream"

#: Inference calls allowed per window, per client. Reads are cheap and
#: idempotent; a generation is neither, and one authenticated caller in a loop
#: is the same outage as an unauthenticated one.
ASK_LIMIT: Final[int] = 20
ASK_WINDOW_SECONDS: Final[float] = 60.0


def _configured_token() -> str:
    return (settings.api_auth_token or "").strip()


def presented_token(request: Request) -> str | None:
    """The credential on this request, from either accepted header.

    `X-API-Key` for scripts and probes, `Authorization: Bearer` because that is
    what every HTTP client already knows how to send.
    """
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    #: `EventSource` cannot set headers, so the SSE stream — and only it —
    #: may carry its credential in the query string. A token in a URL can
    #: reach a proxy log, so the exception is one read-only endpoint wide.
    if request.url.path == STREAM_PATH:
        query_token = request.query_params.get("token")
        if query_token:
            return query_token.strip()
    authorization = request.headers.get("authorization") or ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def require_token(request: Request) -> None:
    """Reject a request that cannot present the configured token.

    Compared with `hmac.compare_digest`: a token check that returns early on
    the first wrong byte tells an attacker how much of it was right.
    """
    expected = _configured_token()
    if not expected:
        return
    if request.url.path in PUBLIC_PATHS:
        return
    offered = presented_token(request)
    if offered is None or not hmac.compare_digest(offered, expected):
        raise HTTPException(status_code=401, detail="missing or invalid API token")


class RateLimiter:
    """Fixed-window request counter, per client.

    In-process and deliberately so: the API is one process on one box, and a
    Redis round trip to rate limit a Redis-backed service adds a dependency to
    the path that is supposed to protect it.
    """

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def reset(self) -> None:
        """Forget every counted call.

        The limiter is process-global, which is right for one API process and
        wrong for a test suite: without this, the twentieth `/brain/ask` in a
        run refuses the twenty-first in an unrelated test file.
        """
        self._hits.clear()

    def check(self, client: str, *, now: float | None = None) -> bool:
        """True when this call is allowed, recording it. False when it is not."""
        moment = time.monotonic() if now is None else now
        hits = self._hits.setdefault(client, deque())
        cutoff = moment - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(moment)
        return True


ask_limiter = RateLimiter(limit=ASK_LIMIT, window_seconds=ASK_WINDOW_SECONDS)


def client_key(request: Request) -> str:
    """Who to count against. The token when there is one, else the peer address."""
    offered = presented_token(request)
    if offered:
        return f"token:{offered[:8]}"
    return f"host:{request.client.host if request.client else 'unknown'}"


def limit_inference(request: Request) -> None:
    """Guard the one endpoint that costs a generation."""
    if not ask_limiter.check(client_key(request)):
        raise HTTPException(status_code=429, detail="too many inference requests")


def log_exposure() -> None:
    """Say plainly, at startup, whether anything is guarding this API."""
    if _configured_token():
        logger.info("API authentication enabled")
        return
    logger.warning(
        "API is UNAUTHENTICATED: every endpoint, including /brain/ask, answers "
        "anything that can reach the port. Set API_AUTH_TOKEN in .env before "
        "exposing this beyond localhost."
    )
