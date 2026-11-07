import inspect
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest

from backend.app.evaluator import LLMRejectedError, LLMUnavailableError
from backend.app.evaluator.client import MAX_TOKENS, AnthropicClient

REQ = httpx.Request("POST", "https://x")
SCHEMA = {"type": "object"}


class FakeSDK:
    def __init__(self, content=None, exc=None, stop_reason="end_turn"):
        self.kwargs, self.exc, self.content, self.stop_reason = None, exc, content, stop_reason
        self.messages = self

    def create(self, **kwargs):
        # Реальная сигнатура установленного SDK: неизвестный параметр падает здесь, как упал бы вживую.
        inspect.signature(anthropic.resources.messages.Messages.create).bind(None, **kwargs)
        if self.exc:
            raise self.exc
        self.kwargs = kwargs
        usage = NS(
            input_tokens=10, output_tokens=5, cache_creation_input_tokens=100, cache_read_input_tokens=None
        )
        content = self.content or [NS(type="text", text='{"results": []}')]
        return NS(content=content, usage=usage, stop_reason=self.stop_reason)


def status_error(cls, code):
    return cls("СЕКРЕТНОЕ_ТЕЛО", response=httpx.Response(code, request=REQ, text="СЕКРЕТНОЕ_ТЕЛО"), body=None)


def test_fake_sdk_rejects_unsupported_kwargs():
    sig = inspect.signature(anthropic.resources.messages.Messages.create)
    for bad in ({"temperature": 0}, {"no_such_param": 1}):
        with pytest.raises(TypeError):
            sig.bind(None, **bad)


def test_request_shape_and_reply():
    sdk = FakeSDK(
        [
            NS(type="thinking", text="СКРЫТО"),
            NS(type="text", text='{"results":'),
            NS(type="text", text=" []}"),
        ]
    )
    resp = AnthropicClient("m-1", "key", sdk_client=sdk).complete("SYS", "USR", SCHEMA)
    k = sdk.kwargs
    assert k["model"] == "m-1" and k["max_tokens"] == MAX_TOKENS == 8192
    assert k["system"] == "SYS" and k["messages"] == [{"role": "user", "content": "USR"}]
    assert k["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    for forbidden in ("temperature", "tool_choice", "tools"):
        assert forbidden not in k
    assert "cache_control" not in repr(k)
    assert resp.text == '{"results": []}' and "СКРЫТО" not in resp.text  # только блоки text
    assert (resp.input_tokens, resp.output_tokens, resp.stop_reason) == (110, 5, "end_turn")


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_stop_reason_passed_through(stop):
    resp = AnthropicClient("m", "k", sdk_client=FakeSDK(stop_reason=stop)).complete("s", "u", SCHEMA)
    assert resp.stop_reason == stop


@pytest.mark.parametrize(
    ("exc", "cls", "code"),
    [
        (anthropic.APIConnectionError(request=REQ), LLMUnavailableError, None),
        (anthropic.APITimeoutError(request=REQ), LLMUnavailableError, None),
        (status_error(anthropic.RateLimitError, 429), LLMUnavailableError, 429),
        (status_error(anthropic.InternalServerError, 500), LLMUnavailableError, 500),
        (status_error(anthropic.APIStatusError, 529), LLMUnavailableError, 529),
        (status_error(anthropic.BadRequestError, 400), LLMRejectedError, 400),
        (status_error(anthropic.AuthenticationError, 401), LLMRejectedError, 401),
        (status_error(anthropic.PermissionDeniedError, 403), LLMRejectedError, 403),
        (status_error(anthropic.NotFoundError, 404), LLMRejectedError, 404),
    ],
)
def test_sdk_errors_mapped_without_leaking_body(exc, cls, code):
    with pytest.raises(cls) as ei:
        AnthropicClient("m", "k", sdk_client=FakeSDK(exc=exc)).complete("s", "u", SCHEMA)
    assert type(ei.value) is cls and ei.value.status_code == code
    assert "СЕКРЕТНОЕ" not in str(ei.value) and (code is None or str(code) in str(ei.value))
    assert ei.value.retryable is (cls is LLMUnavailableError)


def test_constructor_requires_model_and_key():
    with pytest.raises(ValueError):
        AnthropicClient("", "k")
    with pytest.raises(ValueError):
        AnthropicClient("m", "")
