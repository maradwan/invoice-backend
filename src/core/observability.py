import logging
import os
import socket
import time
from urllib.parse import urlparse

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from core.usecase_observability import record_route_request, route_template_from_scope


logger = logging.getLogger(__name__)


class RouteMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - started
            route = route_template_from_scope(request.scope)
            record_route_request(
                route=route,
                method=request.method,
                status_code=status_code,
                duration_seconds=duration,
            )


def _is_enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_host_port(endpoint: str) -> tuple[str, int] | tuple[None, None]:
    """Parse OTLP endpoint into host/port for reachability checks."""
    parsed = urlparse(endpoint)
    if parsed.scheme:
        return parsed.hostname, parsed.port or 4317

    if ":" not in endpoint:
        return endpoint, 4317

    host, port = endpoint.rsplit(":", 1)
    try:
        return host, int(port)
    except ValueError:
        return None, None


def _wait_for_otlp_endpoint(endpoint: str, timeout_seconds: float = 20.0) -> bool:
    """Wait briefly until the OTLP collector socket is reachable."""
    host, port = _parse_host_port(endpoint)
    if not host or not port:
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(1.0)
    return False


def setup_observability(app: FastAPI) -> None:
    """Initialize tracing and metrics for FastAPI when enabled by env vars."""
    app.add_middleware(RouteMetricsMiddleware)

    metrics_enabled = _is_enabled(os.getenv("PROMETHEUS_METRICS_ENABLED", "true"))
    if metrics_enabled:
        metrics_path = os.getenv("PROMETHEUS_METRICS_PATH", "/metrics")
        Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint=metrics_path)
        logger.info("Prometheus metrics enabled", extra={"metrics_path": metrics_path})

    enabled = _is_enabled(os.getenv("OTEL_ENABLED", "false"))
    if not enabled:
        logger.info("OpenTelemetry is disabled. Set OTEL_ENABLED=true to enable tracing.")
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "invoice-backend")
    resource = Resource.create({SERVICE_NAME: service_name})
    tracer_provider = TracerProvider(resource=resource)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    insecure = _is_enabled(os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true"))

    collector_ready = _wait_for_otlp_endpoint(otlp_endpoint)
    if not collector_ready:
        logger.warning(
            "OTLP collector endpoint is not reachable yet (endpoint=%s). "
            "Tracing will still initialize and exporter retries will continue in background.",
            otlp_endpoint,
        )

    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=insecure)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(tracer_provider)
    FastAPIInstrumentor.instrument_app(app)

    logger.info(
        "OpenTelemetry tracing enabled (service=%s, endpoint=%s, insecure=%s)",
        service_name,
        otlp_endpoint,
        insecure,
    )
