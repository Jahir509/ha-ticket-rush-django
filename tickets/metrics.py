"""
Prometheus metrics for the Django twin.

Metric names and label names deliberately match what
prometheus_fastapi_instrumentator exports on the FastAPI side, so one
dashboard and one set of PromQL queries cover both apps and the only thing
that differs is the `job` label.
"""
import os
import time

from django.http import HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

# Buckets, not the library defaults. The default set starts at 5 ms and this
# app answers in 1.5 ms, so every observation would land in the first bucket
# and every quantile would be a straight line. Everything interesting here
# happens below 10 ms.
LATENCY_BUCKETS = (
    0.0005, 0.001, 0.0025, 0.005, 0.0075,
    0.01, 0.025, 0.05, 0.075,
    0.1, 0.25, 0.5, 0.75,
    1.0, 2.5, 5.0, 10.0,
    float("inf"),
)

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "handler", "status"],
)

DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "handler"],
    buckets=LATENCY_BUCKETS,
)

# The saturation signal that matters for sync workers. Each gunicorn sync
# worker serves one request at a time, so when this gauge reaches the worker
# count every worker is busy and new requests are queueing in the kernel.
# livesum adds up the live children and drops dead ones.
IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Requests currently being processed.",
    multiprocess_mode="livesum",
)


class PrometheusMiddleware:
    """Times every request and labels it by URL pattern."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/metrics":
            return self.get_response(request)

        IN_FLIGHT.inc()
        start = time.perf_counter()
        # Set before the call: a gunicorn timeout raises SystemExit, which
        # "except Exception" does not catch, and the finally block below
        # would then hit an unbound name.
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
        finally:
            elapsed = time.perf_counter() - start
            IN_FLIGHT.dec()
            handler = self._handler(request)
            REQUESTS.labels(request.method, handler, str(status)).inc()
            DURATION.labels(request.method, handler).observe(elapsed)

        return response

    @staticmethod
    def _handler(request):
        """
        The URL pattern, never request.path. Labelling with the raw path
        would mint a new time series for every event_id that has ever been
        bought from, and a few thousand of those is enough to bring
        Prometheus down.
        """
        match = getattr(request, "resolver_match", None)
        if match is None:
            return "<unmatched>"
        return match.route or match.url_name or "<unnamed>"


def metrics_view(request):
    """
    Exposition endpoint.

    With 17 gunicorn workers each process keeps its own registry, so a plain
    scrape would hit one random worker and report roughly a seventeenth of
    the traffic. MultiProcessCollector reads the files every worker writes
    into PROMETHEUS_MULTIPROC_DIR and sums them.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        from prometheus_client import REGISTRY as registry

    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)