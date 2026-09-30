"""Request id format."""

from app.utils.ids import generate_request_id, resolve_request_id


def test_generated_ids_match_the_public_format() -> None:
    request_id = generate_request_id()
    assert resolve_request_id(request_id) == request_id


def test_invalid_caller_ids_are_replaced() -> None:
    injected = 'req_ok\n{"event":"forged"}'
    resolved = resolve_request_id(injected)
    assert resolved != injected
    assert resolved.startswith("req_")
    assert "\n" not in resolved
