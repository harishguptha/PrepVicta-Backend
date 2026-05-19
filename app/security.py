import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

logger = logging.getLogger(__name__)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Small in-process API protection layer for size, origin, and abuse checks."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.settings = get_settings()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in {"/health", "/ready"}:
            return await call_next(request)

        if self._request_too_large(request):
            logger.warning("request_rejected_too_large", extra={"path": request.url.path})
            return Response("Request body too large", status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        if self.settings.enforce_origin and not self._origin_allowed(request):
            logger.warning(
                "request_rejected_origin",
                extra={"path": request.url.path, "origin": request.headers.get("origin")},
            )
            return Response("Forbidden", status_code=status.HTTP_403_FORBIDDEN)

        if self._rate_limited(request):
            logger.warning("request_rate_limited", extra={"path": request.url.path})
            return Response("Too many requests", status_code=status.HTTP_429_TOO_MANY_REQUESTS)

        return await call_next(request)

    def _request_too_large(self, request: Request) -> bool:
        content_length = request.headers.get("content-length")
        if not content_length:
            return False
        try:
            return int(content_length) > self.settings.max_request_bytes
        except ValueError:
            return True

    def _origin_allowed(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        referer = request.headers.get("referer", "")
        if origin:
            return origin in self.settings.allowed_origins
        return any(referer.startswith(allowed) for allowed in self.settings.allowed_origins)

    def _rate_limited(self, request: Request) -> bool:
        client_host = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        key = forwarded_for or client_host
        now = time.monotonic()
        window_start = now - 60
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= self.settings.rate_limit_per_minute:
            return True
        hits.append(now)
        return False
