import time
from typing import Optional

from prometheus_client import Counter, Histogram


APP_ROUTE_REQUESTS_TOTAL = Counter(
    "app_route_requests_total",
    "HTTP requests handled by route template",
    labelnames=("route", "method", "status_class"),
)

APP_ROUTE_REQUEST_DURATION_SECONDS = Histogram(
    "app_route_request_duration_seconds",
    "HTTP request duration by route template",
    labelnames=("route", "method", "status_class"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13),
)

INVOICE_PROCESSING_TOTAL = Counter(
    "invoice_processing_total",
    "Invoice processing operations by stage",
    labelnames=("stage", "status", "file_type"),
)

INVOICE_PROCESSING_DURATION_SECONDS = Histogram(
    "invoice_processing_duration_seconds",
    "Invoice processing operation duration by stage",
    labelnames=("stage", "status", "file_type"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55),
)

SUPPLIER_MATCH_TOTAL = Counter(
    "supplier_match_total",
    "Supplier invoice item matching operations",
    labelnames=("status",),
)

SUPPLIER_MATCH_ITEMS_TOTAL = Counter(
    "supplier_match_items_total",
    "Supplier matching item outcomes",
    labelnames=("match",),
)


def route_template_from_scope(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path

    raw_path = scope.get("path", "unknown")
    if not raw_path:
        return "unknown"
    return raw_path


def status_class_from_code(status_code: int) -> str:
    if status_code < 100:
        return "unknown"
    return f"{status_code // 100}xx"


def record_route_request(route: str, method: str, status_code: int, duration_seconds: float) -> None:
    status_class = status_class_from_code(status_code)
    APP_ROUTE_REQUESTS_TOTAL.labels(route=route, method=method, status_class=status_class).inc()
    APP_ROUTE_REQUEST_DURATION_SECONDS.labels(
        route=route,
        method=method,
        status_class=status_class,
    ).observe(duration_seconds)


def record_invoice_processing(stage: str, status: str, file_type: str, duration_seconds: Optional[float] = None) -> None:
    INVOICE_PROCESSING_TOTAL.labels(stage=stage, status=status, file_type=file_type).inc()
    if duration_seconds is not None:
        INVOICE_PROCESSING_DURATION_SECONDS.labels(
            stage=stage,
            status=status,
            file_type=file_type,
        ).observe(duration_seconds)


def record_supplier_match(status: str, matched_count: int, unmatched_count: int) -> None:
    SUPPLIER_MATCH_TOTAL.labels(status=status).inc()
    if matched_count > 0:
        SUPPLIER_MATCH_ITEMS_TOTAL.labels(match="matched").inc(matched_count)
    if unmatched_count > 0:
        SUPPLIER_MATCH_ITEMS_TOTAL.labels(match="unmatched").inc(unmatched_count)


def monotonic_seconds() -> float:
    return time.perf_counter()
