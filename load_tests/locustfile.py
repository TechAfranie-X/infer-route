"""Load tests for InferRoute.

Choose a scenario with ``INFERROUTE_SCENARIO``:

- ``baseline`` — varied prompts, temperature 0.7, no streaming
- ``cache`` — one deterministic prompt repeated at temperature 0
- ``streaming`` — token streams; TTFT is read from ``X-InferRoute-TTFT-Ms``
- ``provider_failure`` — marks mock provider A as failing for the duration of the run
- ``provider_slow`` — marks mock provider A as slow for the duration of the run

``MOCK_A_URL`` defaults to ``http://localhost:8081`` for the failure and slow scenarios.
"""

from __future__ import annotations

import os
from random import randint

import httpx
from locust import HttpUser, between, events, task

SCENARIO = os.environ.get("INFERROUTE_SCENARIO", "baseline")
MOCK_A_URL = os.environ.get("MOCK_A_URL", "http://localhost:8081")
TTFT_SAMPLES: list[float] = []


def _set_mock_mode(mode: str) -> None:
    if SCENARIO not in {"provider_failure", "provider_slow"}:
        return
    httpx.post(f"{MOCK_A_URL.rstrip('/')}/mock/mode", json={"mode": mode}, timeout=5)


@events.test_start.add_listener
def on_test_start(environment, **_kwargs: object) -> None:
    del environment
    if SCENARIO == "provider_failure":
        _set_mock_mode("failing")
    elif SCENARIO == "provider_slow":
        _set_mock_mode("slow")


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs: object) -> None:
    del environment
    if SCENARIO in {"provider_failure", "provider_slow"}:
        _set_mock_mode("healthy")
    if not TTFT_SAMPLES:
        return
    ordered = sorted(TTFT_SAMPLES)

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]

    print(
        "TTFT ms "
        f"count={len(ordered)} "
        f"p50={percentile(0.50):.2f} "
        f"p95={percentile(0.95):.2f} "
        f"p99={percentile(0.99):.2f}"
    )


class InferenceUser(HttpUser):
    wait_time = between(0.01, 0.05)

    @task
    def chat(self) -> None:
        if SCENARIO == "cache":
            payload = _payload("Explain distributed systems simply.", temperature=0, stream=False)
            self.client.post("/v1/chat/completions", json=payload, name="cache")
            return
        if SCENARIO == "streaming":
            payload = _payload(
                f"Stream explanation {randint(1, 10_000)}",
                temperature=0.7,
                stream=True,
            )
            with self.client.post(
                "/v1/chat/completions",
                json=payload,
                name="stream",
                stream=True,
                catch_response=True,
            ) as response:
                ttft = response.headers.get("X-InferRoute-TTFT-Ms")
                if ttft:
                    TTFT_SAMPLES.append(float(ttft))
                for _line in response.iter_lines():
                    pass
                if response.status_code >= 400:
                    response.failure(f"HTTP {response.status_code}")
                else:
                    response.success()
            return
        payload = _payload(
            f"Explain request {randint(1, 1_000_000)}",
            temperature=0.7,
            stream=False,
        )
        self.client.post("/v1/chat/completions", json=payload, name=SCENARIO)


def _payload(content: str, *, temperature: float, stream: bool) -> dict[str, object]:
    return {
        "model": "general",
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "max_tokens": 64,
        "stream": stream,
    }
