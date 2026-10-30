"""
OpenTelemetry SDK bootstrap for La Fabrique backend services.

Call ``configure_telemetry(service_name)`` once at process start — for example
inside the FastAPI lifespan handler or at module load for the agent worker.
The function is **idempotent**: subsequent calls after the first are no-ops, so
it is safe to call from both ``app/main.py`` and ``agents/graph.py``.

Context propagation
-------------------
W3C ``traceparent`` / ``tracestate`` headers are used automatically by the
instrumentation libraries, enabling end-to-end traces across:

    VS Code Daemon → Backend API → LangGraph agents → LLM Proxy → Gemini/DeepSeek

Exporter
--------
OTLP/HTTP is chosen over gRPC because it works through any HTTP reverse proxy
and is natively supported by Jaeger (≥ 1.35), Grafana Tempo, and the
OpenTelemetry Collector without extra plugins.

Environment variables
---------------------
``OTEL_EXPORTER_OTLP_ENDPOINT``
    Base URL of the OTLP/HTTP collector (default: ``http://localhost:4318``).
    Do **not** include ``/v1/traces``; this module appends the path.

``OTEL_SERVICE_NAME``
    Override the service name at runtime (takes precedence over the
    ``service_name`` argument passed to ``configure_telemetry``).
"""

import os
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)

# Guard so the global TracerProvider is set only once per process.
_provider_configured: bool = False

# Default OTLP/HTTP endpoint — matches the standard OpenTelemetry Collector port.
_DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_otlp_endpoint() -> str | None:
    if _is_truthy(os.getenv("OTEL_SDK_DISABLED")):
        return None

    explicit_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if explicit_endpoint:
        return explicit_endpoint.rstrip("/")

    if _is_truthy(os.getenv("OTEL_EXPORTER_OTLP_ENABLED")):
        return _DEFAULT_OTLP_ENDPOINT

    return None


def configure_telemetry(service_name: str) -> None:
    """
    Initialise the global ``TracerProvider`` with a batching OTLP/HTTP exporter.

    This is the single place where tracing infrastructure is wired up.  It must
    be called before any ``trace.get_tracer()`` invocations that should produce
    real (non-no-op) spans.

    Args:
        service_name: Value written to the ``service.name`` resource attribute
                      visible in the Jaeger / Tempo service dropdown.  Can be
                      overridden at runtime via the ``OTEL_SERVICE_NAME``
                      environment variable.
    """
    global _provider_configured
    if _provider_configured:
        return

    # Honour the standard OTel env-var override.
    service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    endpoint_base = _resolve_otlp_endpoint()
    if endpoint_base:
        exporter = OTLPSpanExporter(endpoint=f"{endpoint_base}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _provider_configured = True
    if endpoint_base:
        logger.info(
            "OpenTelemetry configured: service=%s endpoint=%s/v1/traces",
            service_name,
            endpoint_base,
        )
    else:
        logger.info(
            "OpenTelemetry exporter disabled: service=%s (set OTEL_EXPORTER_OTLP_ENDPOINT to enable)",
            service_name,
        )


def get_tracer(name: str) -> trace.Tracer:
    """
    Return an OTel ``Tracer`` bound to *name*.

    Typically called with ``__name__`` so spans are grouped by module in the
    Jaeger UI.  If ``configure_telemetry`` has not been called yet the SDK
    returns a no-op tracer, preventing crashes in unit-test environments.

    Args:
        name: Instrumentation scope name (usually ``__name__``).

    Returns:
        A live or no-op ``Tracer`` instance.
    """
    return trace.get_tracer(name)
