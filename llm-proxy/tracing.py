"""OpenTelemetry for the proxy: spans for every request and outgoing call.

Traces go to an OTLP/HTTP collector only when one is configured
(``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``, ``OTEL_EXPORTER_OTLP_ENDPOINT``, or
``OTEL_EXPORTER_OTLP_ENABLED`` for ``localhost:4318``); ``OTEL_SDK_DISABLED``
turns exporting off.
"""

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_otlp_endpoint() -> str | None:
    if _is_truthy(os.getenv("OTEL_SDK_DISABLED")):
        return None
    explicit_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if explicit_endpoint:
        return explicit_endpoint.rstrip("/")
    if _is_truthy(os.getenv("OTEL_EXPORTER_OTLP_ENABLED")):
        return "http://localhost:4318"
    return None


def instrument(app):
    """Instrument *app* and outgoing requests; return the proxy's tracer."""
    resource = Resource.create({SERVICE_NAME: "llm-proxy"})
    tracer_provider = TracerProvider(resource=resource)
    endpoint_base = _resolve_otlp_endpoint()
    logger = logging.getLogger("llm-proxy")
    if endpoint_base:
        logger.info("OpenTelemetry exporter enabled for llm-proxy: %s/v1/traces", endpoint_base)
        otlp_exporter = OTLPSpanExporter(endpoint=endpoint_base + "/v1/traces")
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)
    else:
        logger.info("OpenTelemetry exporter disabled for llm-proxy")
    trace.set_tracer_provider(tracer_provider)
    FlaskInstrumentor().instrument_app(app)
    RequestsInstrumentor().instrument()
    return trace.get_tracer("app")
