"""Health and readiness over the ASGI app."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import InferRouteError
from app.main import create_app
from tests.fakes import FakeRedis


def test_health_is_ok_when_redis_answers(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "inferroute"
    assert body["redis"] == "connected"
    assert body["version"] == "0.1.0"
    assert response.headers["X-Request-ID"].startswith("req_")


def test_ready_is_ok_when_redis_answers(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["redis"] == "connected"


def test_caller_request_id_is_echoed_when_valid(client: TestClient) -> None:
    request_id = "req_abc123def456"
    response = client.get("/health", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] == request_id


def test_health_stays_up_when_redis_is_down(
    settings: Settings,
) -> None:
    redis = FakeRedis(healthy=False)
    application = create_app(settings=settings, redis_client=redis, providers=[])
    with TestClient(application) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "unavailable"


def test_ready_fails_when_redis_is_down(settings: Settings) -> None:
    application = create_app(
        settings=settings,
        redis_client=FakeRedis(healthy=False),
        providers=[],
    )
    with TestClient(application) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["redis"] == "unavailable"


def test_known_gateway_errors_keep_their_code(settings: Settings) -> None:
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[])

    @application.get("/_test/gateway-error")
    async def gateway_error() -> None:
        raise InferRouteError("The request could not be completed.")

    with TestClient(application) as client:
        response = client.get("/_test/gateway-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.headers["X-Request-ID"].startswith("req_")


def test_request_validation_is_not_reported_as_an_internal_error(settings: Settings) -> None:
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[])

    @application.get("/_test/needs-int")
    async def needs_int(n: int) -> dict[str, int]:
        return {"n": n}

    with TestClient(application) as client:
        response = client.get("/_test/needs-int", params={"n": "abc"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_unhandled_errors_hide_internal_detail(settings: Settings) -> None:
    application = create_app(settings=settings, redis_client=FakeRedis(), providers=[])

    @application.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("redis password=super-secret")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/_test/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "super-secret" not in response.text
    assert response.headers["X-Request-ID"].startswith("req_")


def test_lifespan_closes_redis_client(settings: Settings) -> None:
    redis = FakeRedis()
    application = create_app(settings=settings, redis_client=redis, providers=[])
    with TestClient(application):
        assert redis.pings >= 1
    assert redis.closed is True
