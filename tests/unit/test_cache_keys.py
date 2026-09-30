"""Cache key canonicalization and eligibility."""

from app.models.requests import ChatCompletionRequest, ChatMessage
from app.services.cache import is_cache_eligible
from app.utils.hashing import canonical_request, response_cache_key


def _request(**overrides: object) -> ChatCompletionRequest:
    payload: dict[str, object] = {
        "model": "general",
        "messages": [ChatMessage(role="user", content="Explain distributed systems simply.")],
        "temperature": 0,
        "max_tokens": 200,
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


def test_identical_requests_share_a_key() -> None:
    assert response_cache_key(_request()) == response_cache_key(_request())
    assert response_cache_key(_request()).startswith("inferroute:response:")


def test_prompt_and_parameters_change_the_key() -> None:
    base = response_cache_key(_request())
    other_prompt = response_cache_key(
        _request(messages=[ChatMessage(role="user", content="A different prompt.")])
    )
    other_tokens = response_cache_key(_request(max_tokens=16))
    other_model = response_cache_key(_request(model="other"))
    assert len({base, other_prompt, other_tokens, other_model}) == 4


def test_canonical_form_is_stable() -> None:
    again = canonical_request(_request())
    assert canonical_request(_request()) == again
    assert "Explain distributed systems simply." in again


def test_only_temperature_zero_is_eligible() -> None:
    assert is_cache_eligible(_request(temperature=0)) is True
    assert is_cache_eligible(_request(temperature=0.7)) is False
    assert is_cache_eligible(_request(temperature=0, stream=True)) is False
