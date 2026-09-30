# Load tests

Locust drives the gateway at `POST /v1/chat/completions`. Start the stack first:

```bash
docker compose up --build
```

Interactive UI:

```bash
locust -f load_tests/locustfile.py --host http://localhost:8000
```

Headless example:

```bash
locust \
  -f load_tests/locustfile.py \
  --host http://localhost:8000 \
  --headless \
  -u 100 \
  -r 10 \
  -t 2m
```

## Scenarios

| Scenario | Command | What to look at |
|---|---|---|
| Baseline | `INFERROUTE_SCENARIO=baseline` | RPS, p50/p95/p99, failure rate with healthy providers |
| Cache-heavy | `INFERROUTE_SCENARIO=cache` | Cache hit rate on `/metrics`, lower latency, less provider traffic |
| Provider slow | `INFERROUTE_SCENARIO=provider_slow` | Provider A latency rises; latency-aware routing prefers B and C |
| Provider failure | `INFERROUTE_SCENARIO=provider_failure` | Retries, fallbacks, A becomes unhealthy, requests still succeed |
| Recovery | set A back to `healthy` after a failure run | Probe restores A; traffic returns after cooldown |
| Streaming | `INFERROUTE_SCENARIO=streaming` | TTFT printed at the end of the run, plus full stream time in Locust |

Provider A is controlled at `http://localhost:8081/mock/mode`. Override with `MOCK_A_URL`.

```bash
curl -s -X POST http://localhost:8081/mock/mode \
  -H 'content-type: application/json' \
  -d '{"mode":"slow"}'
```

Modes: `healthy`, `slow`, `failing`, `offline`.

After a failure run, restore A and watch `GET /health/providers` move it from `unhealthy` back to `healthy` once the cooldown elapses and the probe succeeds.

Record measured numbers in `docs/benchmark-results.md`. Do not copy illustrative numbers into that file.
