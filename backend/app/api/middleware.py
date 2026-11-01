"""HTTP middleware: request correlation and access logging."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, request_id_var
from app.core.metrics import describe_route, observe_http, observe_latency

logger = get_logger("gatevision.access")

# Endpoints that are polled every few seconds must not dominate the metrics.
_METRIC_EXCLUDED = ("/metrics", "/media")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and log a structured access line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id")
        request_id = incoming if incoming and len(incoming) <= 64 else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.exception(
                "%s %s failed after %sms", request.method, request.url.path, duration_ms
            )
            _record_request_metric(request, started, 500)
            raise
        else:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time-ms"] = str(duration_ms)
            _record_request_metric(request, started, response.status_code)
            if not request.url.path.startswith(("/media", "/health")):
                logger.info(
                    "%s %s -> %s (%sms)",
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                )
            return response
        finally:
            request_id_var.reset(token)


def _record_request_metric(request: Request, started: float, status_code: int) -> None:
    """Record request count/latency using the resolved route template.

    Post-call the router has stored the matched ``APIRoute`` on the scope, so
    path parameters are collapsed (``/residents/{resident_id}``) and metric
    cardinality stays bounded.
    """
    route = getattr(request.scope.get("route"), "path", None)
    metric_route = describe_route(str(route or request.url.path))
    if metric_route.startswith(_METRIC_EXCLUDED):
        return
    try:
        observe_http(request.method, metric_route, status_code)
        observe_latency(request.method, metric_route, time.perf_counter() - started)
    except Exception:  # pragma: no cover - metrics must never break a request
        logger.debug("Failed to record request metric", exc_info=True)
