import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

SENSITIVE_KEYS = {"password", "token", "credential", "authorization", "api_key", "secret"}


class JsonFormatter(logging.Formatter):
    """Minimal structured JSON formatter for production logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
            "time": self.formatTime(record, self.datefmt),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if key.lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Adds correlation IDs, timing logs, and safe response headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        token = correlation_id_var.set(correlation_id)
        started_at = time.perf_counter()
        logger = logging.getLogger("app.request")

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={"path": request.url.path, "method": request.method},
            )
            raise
        finally:
            correlation_id_var.reset(token)

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
