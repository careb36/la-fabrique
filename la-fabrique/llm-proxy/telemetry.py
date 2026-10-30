"""
OpenTelemetry SDK bootstrap for the La Fabrique LLM Proxy.

Call ``configure_telemetry()`` once at Flask application startup.  The proxy
registers as service ``fabrique-llm-proxy`` so its spans appear as a distinct
service node in the Jaeger service graph, downstream of the backend agents.

Instrumentation applied by ``configure_telemetry()``:
- ``FlaskInstrumentor``    — auto-spans every HTTP request with method, path,
                             status code, and W3C traceparent propagation.
- ``RequestsInstrumentor`` — auto-injects ``traceparent`` into every outbound
                             ``requests`` call (Gemini / DeepSeek APIs), making
                             the full LLM round-trip visible in traces.

Environment variables
---------------------
``OTEL_EXPORTER_OTLP_ENDPOINT``
    Base URL of the OTLP/HTTP collector (default: ``http://localhost:4318``).
``OTEL_SERVICE_NAME``
    Runtime override for the service name.
"""

import os
import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

logger = logging.getLogger(__name__)

_DEFAULT_SERVICE_NAME = "fabrique-llm-proxy"
_DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"

_provider_configured: bool = False


def configure_telemetry(flask_app) -> None:
    """
    Wire up OTel tracing for the Flask proxy application.

    Sets the global ``TracerProvider``, then instruments Flask (inbound HTTP)
    and ``requests`` (outbound HTTP to Gemini / DeepSeek).

    Args:
        flask_app: The Flask application instance to instrument.
    """
    global _provider_configured
    if _provider_configured:
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", _DEFAULT_SERVICE_NAME)
    endpoint_base = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", _DEFAULT_OTLP_ENDPOINT
    ).rstrip("/")

    resource = Resource.create({SERVICE_NAME: service_name})
    exporter = OTLPSpanExporter(endpoint=f"{endpoint_base}/v1/traces")

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Instrument Flask — auto-creates a server span for every inbound request
    # and reads the W3C traceparent header to continue distributed traces
    # started by the backend agents.
    FlaskInstrumentor().instrument_app(flask_app)

    # Instrument requests — auto-injects traceparent into every outbound call
    # so Gemini / DeepSeek calls appear as child spans in the trace.
    RequestsInstrumentor().instrument()

    _provider_configured = True
    logger.info(
        "OpenTelemetry configured: service=%s endpoint=%s/v1/traces",
        service_name,
        endpoint_base,
    )


def get_tracer(name: str) -> trace.Tracer:
    """Return an OTel Tracer bound to *name* (typically ``__name__``)."""
    return trace.get_tracer(name)
