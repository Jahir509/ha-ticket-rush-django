"""
Prometheus metrics for the Django twin.

Request metrics are recorded by the middleware on every request and kept in
the multiprocess files, one set per gunicorn worker. VM and Postgres
metrics are computed at scrape time by tickets/collectors.py. One scrape of
/metrics returns all three.
"""
import os
import time

from django.db import connection
from django.http import HttpResponse
from prometheus_client import (CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry,
                               Counter, Gauge, Histogram, generate_latest,
                               multiprocess)

from .collectors import PostgresCollector, SystemCollector

# Starts at 0.5 ms: this app answers in about 3 ms, and the library default
# (from 5 ms) would put every request in the first bucket.
LATENCY_BUCKETS = (
    0.0005, 0.001, 0.0025, 0.005, 0.0075,
    0.01, 0.025, 0.05, 0.075,
    0.1, 0.25, 0.5, 0.75,
    1.0, 2.5, 5.0, 10.0,
    float("inf"),
)
SIZE_BUCKETS = (256, 1024, 4096, 16384, 65536, 262144, 1048576, float("inf"))

REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests.",
    ["method", "handler", "status"])
DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds.",
    ["method", "handler"], buckets=LATENCY_BUCKETS)
RESPONSE_SIZE = Histogram(
    "http_response_size_bytes", "Response body size, before nginx compresses it.",
    ["handler"], buckets=SIZE_BUCKETS)
IN_FLIGHT = Gauge(
    "http_requests_in_flight", "Requests currently being processed.",
    multiprocess_mode="livesum")
EXCEPTIONS = Counter(
    "django_exceptions_total", "Unhandled exceptions raised by views, by type.",
    ["handler", "exception"])
DB_QUERY = Histogram(
    "django_db_query_duration_seconds", "Time of each SQL query a request ran.",
    ["handler"], buckets=LATENCY_BUCKETS)


def _handler(request):
    """The URL pattern, never the raw path: one series per route, not per id."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return "<unmatched>"
    return match.route or match.url_name or "<unnamed>"


class _QueryTimer:
    """Wraps every SQL statement a request runs and keeps its duration."""

    def __init__(self):
        self.durations = []

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.durations.append(time.perf_counter() - start)


class PrometheusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/metrics":
            return self.get_response(request)

        timer = _QueryTimer()
        IN_FLIGHT.inc()
        start = time.perf_counter()
        status, size = 500, None
        try:
            with connection.execute_wrapper(timer):
                response = self.get_response(request)
            status = response.status_code
            if not getattr(response, "streaming", False):
                size = len(response.content)
            return response
        finally:
            elapsed = time.perf_counter() - start
            IN_FLIGHT.dec()
            handler = _handler(request)
            REQUESTS.labels(request.method, handler, str(status)).inc()
            DURATION.labels(request.method, handler).observe(elapsed)
            if size is not None:
                RESPONSE_SIZE.labels(handler).observe(size)
            for seconds in timer.durations:
                DB_QUERY.labels(handler).observe(seconds)

    def process_exception(self, request, exception):
        # Django turns the exception into a 500 before it reaches __call__,
        # so its type is only visible here.
        EXCEPTIONS.labels(_handler(request), type(exception).__name__).inc()
        return None


_COLLECTORS = (SystemCollector(), PostgresCollector())


def metrics_view(request):
    """
    One endpoint, three sources:
      request metrics  summed across every gunicorn worker's files
      VM metrics       read from /proc right now
      Postgres stats   queried right now
    """
    registry = CollectorRegistry()
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.MultiProcessCollector(registry)
        local = b""
    else:
        local = generate_latest(REGISTRY)
    for collector in _COLLECTORS:
        registry.register(collector)
    return HttpResponse(local + generate_latest(registry),
                        content_type=CONTENT_TYPE_LATEST)