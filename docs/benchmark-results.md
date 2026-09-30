# Benchmark results

These numbers were measured on 2026-09-30 against the local Docker Compose stack (`docker compose up --build`). Locust 2.46.6 called `http://localhost:8000`. Each scenario used 20 users, a spawn rate of 10 users per second, and a 20 second limit:

```bash
INFERROUTE_SCENARIO=<scenario> locust \
  -f load_tests/locustfile.py \
  --host http://localhost:8000 \
  --headless \
  -u 20 \
  -r 10 \
  -t 20s \
  --only-summary
```

The gateway process was restarted before baseline, streaming, provider_slow, and provider_failure so in-memory health from the previous scenario did not carry over. Redis was flushed before the cache scenario. Locust's percentile table is labeled approximated. TTFT percentiles are computed in the Locust process from the `X-InferRoute-TTFT-Ms` header of every successful stream in that run.

This is one laptop and a short run. It is not a capacity claim.

## Baseline

Varied prompts, temperature 0.7, no streaming. `ROUTING_STRATEGY=latency_aware`.

| Metric | Measured |
|---|---:|
| Requests | 2297 |
| Failures | 0 (0.00%) |
| Throughput | 125.17 req/s |
| Average | 124 ms |
| Median | 110 ms |
| Min | 100 ms |
| Max | 349 ms |
| p50 | 110 ms |
| p95 | 190 ms |
| p99 | 260 ms |

## Cache

One repeated prompt at temperature 0, after `FLUSHDB`.

| Metric | Measured |
|---|---:|
| Requests | 11826 |
| Failures | 0 (0.00%) |
| Throughput | 596.91 req/s |
| Average | 2 ms |
| Median | 2 ms |
| Min | 0 ms |
| Max | 459 ms |
| p50 | 2 ms |
| p95 | 5 ms |
| p99 | 7 ms |
| `inferroute_cache_hits_total` | 11816 |
| `inferroute_cache_misses_total` | 10 |

Hit rate from those two counters: 11816 / 11826 = 99.92%. The 10 misses are the requests that reached Redis before the first completion was stored.

## Streaming

Varied prompts with `stream: true`. Locust response time is the time until the stream finished. TTFT is the gateway header.

| Metric | Measured |
|---|---:|
| Requests | 2509 |
| Failures | 0 (0.00%) |
| Throughput | 126.17 req/s |
| Average response | 122 ms |
| Median response | 110 ms |
| Min | 101 ms |
| Max | 440 ms |
| Response p50 | 110 ms |
| Response p95 | 190 ms |
| Response p99 | 260 ms |
| TTFT samples | 2509 |
| TTFT p50 | 102.82 ms |
| TTFT p95 | 184.28 ms |
| TTFT p99 | 240.83 ms |

## Provider A slow

Mock provider A was set to `slow` for the run (default slow delay 2000 ms) and restored to `healthy` when Locust stopped.

| Metric | Measured |
|---|---:|
| Requests | 2144 |
| Failures | 0 (0.00%) |
| Throughput | 107.82 req/s |
| Average | 149 ms |
| Median | 110 ms |
| Min | 100 ms |
| Max | 2032 ms |
| p50 | 110 ms |
| p95 | 310 ms |
| p99 | 370 ms |

`GET /health/providers` immediately after the run:

| Provider | Status | EWMA | Requests | Failures |
|---|---|---:|---:|---:|
| provider-a | healthy | 2010.959 ms | 4 | 0 |
| provider-b | healthy | 305.244 ms | 332 | 4 |
| provider-c | healthy | 103.005 ms | 2024 | 204 |

Provider A stayed healthy because slow responses still succeed. After a few samples its EWMA moved to about 2 seconds and almost all later traffic went to provider C. Provider C's failures are its configured 10% random error rate, recovered by retry and fallback.

## Provider A failing

Mock provider A was set to `failing` for the run and restored to `healthy` when Locust stopped. Client-visible failures stayed at zero because requests fell back.

| Metric | Measured |
|---|---:|
| Requests | 2251 |
| Failures | 0 (0.00%) |
| Throughput | 113.15 req/s |
| Average | 140 ms |
| Median | 110 ms |
| Min | 101 ms |
| Max | 504 ms |
| p50 | 110 ms |
| p95 | 310 ms |
| p99 | 380 ms |

`GET /health/providers` immediately after the run:

| Provider | Status | EWMA | Requests | Failures | Cooldown until |
|---|---|---:|---:|---:|---|
| provider-a | unhealthy | 0.000 ms | 8 | 8 | 2026-09-30T18:43:11.360394Z |
| provider-b | healthy | 303.444 ms | 291 | 6 | — |
| provider-c | healthy | 103.864 ms | 2211 | 237 | — |

Prometheus counters from that same process:

| Counter | Value |
|---|---:|
| `inferroute_fallbacks_total{provider="provider-b"}` | 22 |
| `inferroute_retries_total{provider="provider-a"}` | 4 |
| `inferroute_retries_total{provider="provider-b"}` | 6 |
| `inferroute_retries_total{provider="provider-c"}` | 219 |
| `inferroute_provider_errors_total{provider="provider-a"}` | 8 |
| `inferroute_provider_errors_total{provider="provider-b"}` | 6 |
| `inferroute_provider_errors_total{provider="provider-c"}` | 237 |

Provider A was removed from routing after it crossed the unhealthy threshold. Provider C's error and retry counts are dominated by its 10% random failure rate, not by the injected outage on A.
