"""Prometheus metrics for the gateway process.

Labels stay low-cardinality: provider id, status, and routing strategy. Request
ids are logs, not labels. Percentiles come from the histograms here and from
Locust, not from averaging a single request.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


class MetricsService:
    def __init__(self) -> None:
        registry = CollectorRegistry()
        self._registry = registry
        self.requests = Counter(
            "inferroute_requests_total",
            "Chat completion requests by outcome.",
            ["status", "strategy"],
            registry=registry,
        )
        self.request_duration = Histogram(
            "inferroute_request_duration_seconds",
            "End-to-end gateway latency.",
            ["provider", "status"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )
        self.ttft = Histogram(
            "inferroute_ttft_seconds",
            "Time to first streamed token.",
            ["provider"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )
        self.cache_hits = Counter(
            "inferroute_cache_hits_total",
            "Deterministic responses served from Redis.",
            registry=registry,
        )
        self.cache_misses = Counter(
            "inferroute_cache_misses_total",
            "Cache-eligible requests that missed Redis.",
            registry=registry,
        )
        self.retries = Counter(
            "inferroute_retries_total",
            "Local retries against the same provider.",
            ["provider"],
            registry=registry,
        )
        self.fallbacks = Counter(
            "inferroute_fallbacks_total",
            "Requests that moved from one provider to another.",
            ["provider"],
            registry=registry,
        )
        self.provider_requests = Counter(
            "inferroute_provider_requests_total",
            "Attempts sent to a model endpoint.",
            ["provider", "status"],
            registry=registry,
        )
        self.provider_errors = Counter(
            "inferroute_provider_errors_total",
            "Failed attempts sent to a model endpoint.",
            ["provider"],
            registry=registry,
        )

    def render(self) -> bytes:
        return generate_latest(self._registry)
