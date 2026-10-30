"""
Prometheus metrics for the Fabrique Enterprise API.

Exposes application metrics at /metrics endpoint.
"""

import time

from fastapi import Response
from logging_config import logger
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.types import ASGIApp, Receive, Scope, Send

# Request metrics
REQUEST_COUNT = Counter(
    "fabrique_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "fabrique_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

# Active connections
ACTIVE_CONNECTIONS = Gauge(
    "fabrique_active_connections",
    "Number of active connections",
)

# Agent run metrics
AGENT_RUNS_INGESTED = Counter(
    "fabrique_agent_runs_ingested_total",
    "Total agent runs ingested",
    ["producer"],
)

AGENT_RUNS_VERIFIED = Counter(
    "fabrique_agent_runs_verified_total",
    "Total agent runs verified",
    ["verdict"],
)

# Sprint metrics
SPRINTS_CREATED = Counter(
    "fabrique_sprints_created_total",
    "Total sprints created",
    ["scope"],
)

SPRINTS_COMPLETED = Counter(
    "fabrique_sprints_completed_total",
    "Total sprints completed",
    ["status"],
)

# Error metrics
ERRORS_TOTAL = Counter(
    "fabrique_errors_total",
    "Total errors",
    ["type"],
)


def endpoint_label(scope: Scope) -> str:
    """The matched route's template, e.g. ``/v1/sprints/{sprint_id}/board``.

    The raw path would put sprint, task and ticket ids on a public endpoint
    and give every scanned URL its own series, so it is only used when the
    match captured no parameter — that is the case of a plain Starlette route
    (``/docs``, ``/openapi.json``), whose path is fixed and is its own label.
    A request whose match captured a parameter never publishes the path: if the
    template is missing it is counted as ``unmatched``. A CORS preflight is
    answered before any route and counted as ``preflight``.
    """
    route = scope.get("route")
    if route is not None:
        return getattr(route, "path", None) or "unmatched"
    if scope.get("endpoint") is not None:
        if scope.get("path_params"):
            return "unmatched"
        return scope.get("path") or "unmatched"
    if scope.get("method") == "OPTIONS":
        return "preflight"
    return "unmatched"


class MetricsMiddleware:
    """Records one count and one latency sample per HTTP response.

    Plain ASGI on purpose. The route template lives on ``scope["route"]``,
    which the router writes while serving the request; a ``BaseHTTPMiddleware``
    reads that scope from another task after ``call_next`` returns and can miss
    the write, which is what used to send labelled requests down the raw-path
    fallback at random.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ACTIVE_CONNECTIONS.inc()
        start_time = time.perf_counter()
        status = 500

        async def capture_status(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            endpoint = endpoint_label(scope)
            REQUEST_COUNT.labels(
                method=scope["method"],
                endpoint=endpoint,
                status=status,
            ).inc()
            REQUEST_LATENCY.labels(
                method=scope["method"],
                endpoint=endpoint,
            ).observe(time.perf_counter() - start_time)
            ACTIVE_CONNECTIONS.dec()


def setup_metrics(app):
    """Configure metrics middleware and endpoint on the app."""
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics")
    async def metrics_endpoint():
        """Prometheus metrics endpoint."""
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    logger.info("Prometheus metrics configured at /metrics")


# Helper functions for recording metrics
def record_agent_run_ingested(producer: str):
    """Record an agent run ingestion."""
    AGENT_RUNS_INGESTED.labels(producer=producer).inc()


def record_agent_run_verified(verdict: str):
    """Record an agent run verification."""
    AGENT_RUNS_VERIFIED.labels(verdict=verdict).inc()


def record_sprint_created(scope: str):
    """Record a sprint creation."""
    SPRINTS_CREATED.labels(scope=scope).inc()


def record_sprint_completed(status: str):
    """Record a sprint completion."""
    SPRINTS_COMPLETED.labels(status=status).inc()


def record_error(error_type: str):
    """Record an error."""
    ERRORS_TOTAL.labels(type=error_type).inc()
