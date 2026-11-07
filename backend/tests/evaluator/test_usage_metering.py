"""Измерение фактического расхода: served_model, кеш, рассуждения, тариф. Без сети и ключей."""

import dataclasses
import inspect
import logging
from types import SimpleNamespace as NS
from typing import Any

import httpx
import openai
import pytest
from openai.resources.responses import Responses

from backend.app.evaluator import LLMUnavailableError, evaluate
from backend.app.evaluator.client import (
    AnthropicClient,
    Fault,
    LLMResponse,
    MockClient,
    OpenAIClient,
    Prices,
)

SECRET_KEY = "sk-test-NOT-A-REAL-KEY"
FULL = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "cached_tokens": 800,
    "reasoning_tokens": 300,
    "served_model": "gpt-test-2026-01-01",
    "service_tier": "default",
}


def done_line(caplog: pytest.LogCaptureFixture) -> str:
    lines = [r.getMessage() for r in caplog.records if "evaluator_done" in r.getMessage()]
    assert len(lines) == 1
    return lines[0]


# ---------- OpenAIClient ----------


class FakeOpenAI:
    """Фейковый SDK: параметры проверяются по реальной сигнатуре установленного openai."""

    def __init__(self, response: Any) -> None:
        self.response, self.kwargs = response, None
        self.responses = self

    def create(self, **kwargs: Any) -> Any:
        inspect.signature(Responses.create).bind(None, **kwargs)
        self.kwargs = kwargs
        return self.response


def openai_response(**over: Any) -> Any:
    fields: dict[str, Any] = {
        "output_text": '{"results": []}',
        "status": "completed",
        "output": [],
        "incomplete_details": None,
        "model": "gpt-test-2026-01-01",
        "service_tier": "default",
        "usage": NS(
            input_tokens=1000,
            output_tokens=500,
            input_tokens_details=NS(cached_tokens=800, cache_write_tokens=0),
            output_tokens_details=NS(reasoning_tokens=300),
        ),
    }
    return NS(**(fields | over))


def run_openai(response: Any) -> LLMResponse:
    return OpenAIClient("gpt-test", SECRET_KEY, sdk_client=FakeOpenAI(response)).complete("s", "u", {})


def test_openai_collects_all_fields_and_does_not_adjust_totals():
    resp = run_openai(openai_response())
    # input_tokens включает cached_tokens, output_tokens включает reasoning_tokens: суммы как есть
    assert (resp.input_tokens, resp.output_tokens) == (1000, 500)
    assert (resp.cached_tokens, resp.reasoning_tokens) == (800, 300)
    assert (resp.served_model, resp.service_tier, resp.stop_reason) == (
        "gpt-test-2026-01-01",
        "default",
        "end_turn",
    )


def test_openai_request_matches_the_installed_sdk_signature():
    sdk = FakeOpenAI(openai_response())
    OpenAIClient("gpt-test", SECRET_KEY, sdk_client=sdk).complete("SYS", "USR", {"type": "object"})
    assert (
        sdk.kwargs["store"] is False and sdk.kwargs["instructions"] == "SYS" and sdk.kwargs["input"] == "USR"
    )


@pytest.mark.parametrize(
    "response",
    [
        openai_response(usage=NS(input_tokens=10, output_tokens=5)),  # нет блоков details
        openai_response(
            usage=NS(input_tokens=10, output_tokens=5, input_tokens_details=None, output_tokens_details=None)
        ),
        NS(output_text="{}", status="completed", output=[], incomplete_details=None, usage=None),
    ],
)
def test_openai_missing_usage_details_become_none(response):
    resp = run_openai(response)
    assert resp.stop_reason == "end_turn"
    assert resp.cached_tokens is None and resp.reasoning_tokens is None
    if getattr(response, "usage", None) is None:
        assert (resp.input_tokens, resp.output_tokens) == (0, 0)
    else:
        assert (resp.input_tokens, resp.output_tokens) == (10, 5)  # токены есть и без details


@pytest.mark.parametrize(
    "response",
    [
        openai_response(model=None, service_tier=None),
        openai_response(model="  ", service_tier=""),
        NS(output_text="{}", status="completed", output=[], incomplete_details=None, usage=None),  # полей нет
    ],
)
def test_openai_missing_model_and_tier_become_none(response):
    resp = run_openai(response)
    assert resp.served_model is None and resp.service_tier is None


def test_openai_non_numeric_details_are_ignored():
    usage = NS(
        input_tokens=10,
        output_tokens=5,
        input_tokens_details=NS(cached_tokens="много"),
        output_tokens_details=NS(reasoning_tokens=True),
    )
    resp = run_openai(openai_response(usage=usage))
    assert resp.cached_tokens is None and resp.reasoning_tokens is None


def test_openai_labels_are_sanitized_for_logs():
    resp = run_openai(
        openai_response(model="gpt-x\nERROR forged=1 key=" + "z" * 200, service_tier="de fault")
    )
    assert "\n" not in resp.served_model and " " not in resp.served_model and len(resp.served_model) <= 64
    assert " " not in resp.service_tier


def test_openai_error_message_has_no_key_or_body():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://x"))

    class Down:
        responses = NS(create=lambda **kw: (_ for _ in ()).throw(exc))

    with pytest.raises(LLMUnavailableError) as caught:
        OpenAIClient("m", SECRET_KEY, sdk_client=Down()).complete("s", "u", {})
    assert SECRET_KEY not in str(caught.value)


# ---------- AnthropicClient ----------


def test_anthropic_reports_cache_read_as_cached_tokens_without_double_count():
    usage = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=100, cache_read_input_tokens=40)
    sdk = NS(
        messages=NS(
            create=lambda **kw: NS(
                content=[NS(type="text", text="{}")], usage=usage, stop_reason="end_turn", model="claude-test"
            )
        )
    )
    resp = AnthropicClient("m", "k", sdk_client=sdk).complete("s", "u", {})
    assert resp.input_tokens == 10 + 100 + 40  # у Anthropic кеш не входит в input_tokens, поэтому суммируется
    assert (resp.cached_tokens, resp.served_model, resp.reasoning_tokens) == (40, "claude-test", None)


def test_anthropic_missing_optional_fields():
    usage = NS(input_tokens=10, output_tokens=5)
    sdk = NS(messages=NS(create=lambda **kw: NS(content=[], usage=usage, stop_reason="end_turn")))
    resp = AnthropicClient("m", "k", sdk_client=sdk).complete("s", "u", {})
    assert (resp.input_tokens, resp.cached_tokens, resp.served_model, resp.service_tier) == (
        10,
        None,
        None,
        None,
    )


# ---------- evaluate() с MockClient ----------


def test_usage_totals_are_the_reported_totals_and_cost_is_flat(simple_dialog, default_checklist):
    mock = MockClient(default_checklist, response_fields=FULL)
    out = evaluate(simple_dialog, default_checklist, client=mock, model="cfg-model", prices=Prices(2.0, 10.0))
    # cached и reasoning не вычитаются и не прибавляются: стоимость по input_tokens и output_tokens как есть
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.llm_calls) == (1000, 500, 1)
    assert out.usage.cost_usd == pytest.approx((1000 * 2 + 500 * 10) / 1e6)
    assert out.usage.model == "cfg-model"  # имя из настроек, фактическая модель только в логе


def test_logs_have_per_call_and_total_metering(simple_dialog, default_checklist, caplog):
    mock = MockClient(default_checklist, [Fault("bad_json", calls=(1,))], response_fields=FULL)
    with caplog.at_level(logging.DEBUG):
        out = evaluate(simple_dialog, default_checklist, client=mock, model="cfg", prices=Prices(2.0, 10.0))
    assert (out.usage.llm_calls, out.usage.input_tokens, out.usage.output_tokens) == (2, 2000, 1000)
    calls = [r.getMessage() for r in caplog.records if "evaluator_call" in r.getMessage()]
    assert len(calls) == 2 and all("cached_tokens=800 reasoning_tokens=300" in c for c in calls)
    assert all("served_model=gpt-test-2026-01-01 service_tier=default" in c for c in calls)
    total = done_line(caplog)
    assert "cached_tokens=1600 reasoning_tokens=600" in total  # суммы по двум вызовам
    assert "served_models=gpt-test-2026-01-01 " in total and "service_tiers=default" in total
    assert "input_tokens=2000 output_tokens=1000" in total


def test_missing_optional_fields_are_reported_as_unavailable(simple_dialog, default_checklist, caplog):
    mock = MockClient(default_checklist, response_fields={"input_tokens": 50, "output_tokens": 20})
    with caplog.at_level(logging.DEBUG):
        out = evaluate(simple_dialog, default_checklist, client=mock, model="cfg", prices=Prices(1.0, 1.0))
    assert (out.usage.input_tokens, out.usage.output_tokens) == (50, 20)
    total = done_line(caplog)
    assert "served_models=n/a cached_tokens=n/a reasoning_tokens=n/a service_tiers=n/a" in total
    call = next(r.getMessage() for r in caplog.records if "evaluator_call" in r.getMessage())
    assert "cached_tokens=n/a reasoning_tokens=n/a served_model=n/a service_tier=n/a" in call


class Switching:
    """Первый ответ без необязательных полей и с битым JSON, второй с полями и другой моделью."""

    def __init__(self, checklist):
        self.mock, self.n = MockClient(checklist, [Fault("bad_json", calls=(1,))]), 0

    def complete(self, system, user, schema):
        self.n += 1
        base = self.mock.complete(system, user, schema)
        extras = {} if self.n == 1 else {"cached_tokens": 50, "served_model": "m-2", "service_tier": "flex"}
        return dataclasses.replace(base, input_tokens=100, output_tokens=10, **extras)


def test_partially_available_fields_are_summed_over_known_values(simple_dialog, default_checklist, caplog):
    with caplog.at_level(logging.DEBUG):
        evaluate(simple_dialog, default_checklist, client=Switching(default_checklist), model="cfg")
    total = done_line(caplog)
    assert "served_models=m-2 cached_tokens=50 reasoning_tokens=n/a service_tiers=flex" in total


def test_different_served_models_are_listed_once_each(simple_dialog, default_checklist, caplog):
    class TwoModels(Switching):
        def complete(self, system, user, schema):
            resp = super().complete(system, user, schema)
            return dataclasses.replace(resp, served_model="m-1" if self.n == 1 else "m-2")

    with caplog.at_level(logging.DEBUG):
        evaluate(simple_dialog, default_checklist, client=TwoModels(default_checklist), model="cfg")
    assert "served_models=m-1,m-2 " in done_line(caplog)


def test_failure_keeps_metering_of_spent_calls(simple_dialog, default_checklist, caplog):
    class DownAfterOne:
        n = 0

        def complete(self, system, user, schema):
            self.n += 1
            if self.n == 1:
                return LLMResponse("не json", 700, 50, "end_turn", "m-1", 600, 20, "default")
            raise LLMUnavailableError("down", upstream_status=503)

    with caplog.at_level(logging.DEBUG), pytest.raises(LLMUnavailableError) as caught:
        evaluate(
            simple_dialog, default_checklist, client=DownAfterOne(), model="cfg", prices=Prices(2.0, 10.0)
        )
    assert (caught.value.usage.input_tokens, caught.value.usage.output_tokens) == (700, 50)
    total = done_line(caplog)
    assert "served_models=m-1 cached_tokens=600 reasoning_tokens=20 service_tiers=default" in total
    assert "input_tokens=700 output_tokens=50" in total


def test_logs_contain_no_transcript_quotes_or_keys(default_checklist, caplog):
    from .conftest import make_dialog

    dialog = make_dialog(
        ("client", "СЕКРЕТНЫЙ_ВОПРОС_КЛИЕНТА"), ("operator", "СЕКРЕТНЫЙ_ОТВЕТ_ОПЕРАТОРА Здравствуйте")
    )
    mock = MockClient(default_checklist, response_fields=FULL | {"served_model": f"gpt-x\n{SECRET_KEY}"[:20]})
    with caplog.at_level(logging.DEBUG):
        out = evaluate(dialog, default_checklist, client=mock, model="cfg", prices=Prices())
    quotes = [e.quote for r in out.results for e in r.evidence if e.quote]
    assert quotes
    for private in ("СЕКРЕТНЫЙ_ВОПРОС", "СЕКРЕТНЫЙ_ОТВЕТ", SECRET_KEY, *quotes):
        assert private not in caplog.text
