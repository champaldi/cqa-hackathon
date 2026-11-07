import inspect
import logging

import anthropic
import httpx
import pytest

from backend.app.evaluator import (
    EvaluationError,
    LLMUnavailableError,
    NoOperatorTurnsError,
    ValidationFailedError,
    evaluate,
)
from backend.app.evaluator.client import AnthropicClient, Fault, LLMResponse, MockClient, Prices, make_client

from .conftest import make_dialog


def test_mock_happy_path(simple_dialog, default_checklist):
    mock = MockClient()
    out = evaluate(simple_dialog, default_checklist, client=mock)
    assert [r.criterion_id for r in out.results] == [c.id for c in default_checklist.criteria]
    assert out.usage.model == "mock" and out.usage.llm_calls == 1
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cost_usd) == (0, 0, 0)
    for r in out.results:
        for e in r.evidence:
            if e.kind == "quote":
                assert e.quote in simple_dialog.transcript[e.turn_index].text


def test_all_samples_pass_through_mock(fake_dialogs, default_checklist):
    assert len(fake_dialogs) == 4
    for d in fake_dialogs:
        out = evaluate(d, default_checklist, client=MockClient())
        assert len(out.results) == len(default_checklist.criteria), d.conversation_id


def test_mock_na_path_kz_sample(fake_dialogs, default_checklist):
    kz = next(d for d in fake_dialogs if d.conversation_id == "sample-kz-001")
    out = evaluate(kz, default_checklist, client=MockClient(na_criteria=frozenset({"c07"})))
    c07 = next(r for r in out.results if r.criterion_id == "c07")
    assert c07.answer == "na" and c07.evidence[0].kind == "na_reason"


# --- retry ---


@pytest.mark.parametrize(
    "kind",
    [
        "bad_scale_step",
        "fake_quote",
        "illegal_na",
        "missing_criterion",
        "duplicate_criterion",
        "no_tool_block",
    ],
)
def test_single_fault_repaired(simple_dialog, default_checklist, kind):
    mock = MockClient([Fault(kind, calls=(1,))])
    out = evaluate(simple_dialog, default_checklist, client=mock)
    assert out.usage.llm_calls == 2 and len(out.results) == len(default_checklist.criteria)
    if kind in ("duplicate_criterion", "no_tool_block"):  # ответ не по схеме: ошибка всех критериев
        assert mock.requested[1] == mock.requested[0]
    else:
        assert len(mock.requested[1]) == 1  # повторно запрошен только испорченный критерий


def test_only_broken_criterion_requested_again(simple_dialog, default_checklist):
    mock = MockClient([Fault("bad_scale_step", criterion_id="c06", calls=(1,))])
    evaluate(simple_dialog, default_checklist, client=mock)
    assert mock.requested[1] == ["c06"]


def test_persistent_fault_fails_after_two_repair_rounds(simple_dialog, default_checklist):
    mock = MockClient(
        [Fault("fake_quote", criterion_id="c01")],
    )
    with pytest.raises(ValidationFailedError) as ei:
        evaluate(simple_dialog, default_checklist, client=mock)
    assert mock.calls == 3 and mock.requested[1:] == [["c01"], ["c01"]]
    assert ei.value.usage.llm_calls == 3
    assert [e.criterion_id for e in ei.value.errors] == ["c01"]
    assert isinstance(ei.value, EvaluationError)


def test_repair_round_limit_is_configurable(simple_dialog, default_checklist):
    mock = MockClient([Fault("no_tool_block")])
    with pytest.raises(ValidationFailedError):
        evaluate(simple_dialog, default_checklist, client=mock, max_repair_rounds=0)
    assert mock.calls == 1


def test_merge_after_repair_keeps_valid_results(simple_dialog, default_checklist):
    mock = MockClient([Fault("fake_quote", criterion_id="c02", calls=(1,))])
    out = evaluate(simple_dialog, default_checklist, client=mock)
    assert [r.criterion_id for r in out.results] == [c.id for c in default_checklist.criteria]


def test_final_merge_guard_rejects_missing_or_duplicate(simple_dialog, default_checklist, monkeypatch):
    from backend.app.evaluator import core

    real = core.validate_complete
    monkeypatch.setattr(core, "validate_complete", lambda results, cl, turns: real(results[:-1], cl, turns))
    with pytest.raises(ValidationFailedError) as ei:
        evaluate(simple_dialog, default_checklist, client=MockClient())
    assert {e.code for e in ei.value.errors} == {"missing"}
    monkeypatch.setattr(
        core, "validate_complete", lambda results, cl, turns: real([*results, results[0]], cl, turns)
    )
    with pytest.raises(ValidationFailedError) as ei:
        evaluate(simple_dialog, default_checklist, client=MockClient())
    assert {e.code for e in ei.value.errors} == {"duplicate"}


# --- прекек, usage, логи ---


@pytest.mark.parametrize("speakers", [["client", "bot", "system"], []])
def test_no_operator_turns_zero_calls(default_checklist, speakers):
    d = make_dialog(*[(s, "текст") for s in speakers])
    mock = MockClient()
    with pytest.raises(NoOperatorTurnsError):
        evaluate(d, default_checklist, client=mock)
    assert mock.calls == 0


class _Priced:
    def __init__(self):
        self.n = 0

    def complete(self, system, user, tool_schema):
        self.n += 1
        inner = MockClient().complete(system, user, tool_schema)
        return LLMResponse(inner.tool_input if self.n > 1 else None, 1_000_000, 500_000, "test-model")


def test_usage_sums_all_calls_including_invalid(simple_dialog, default_checklist):
    out = evaluate(simple_dialog, default_checklist, client=_Priced(), prices=Prices(3.0, 15.0))
    u = out.usage
    assert (u.llm_calls, u.input_tokens, u.output_tokens, u.model) == (2, 2_000_000, 1_000_000, "test-model")
    assert u.cost_usd == pytest.approx(2 * 3.0 + 1 * 15.0)


def test_llm_unavailable_propagates(simple_dialog, default_checklist):
    class Down:
        def complete(self, *a):
            raise LLMUnavailableError("down")

    with pytest.raises(LLMUnavailableError):
        evaluate(simple_dialog, default_checklist, client=Down())


def test_logs_do_not_contain_texts(default_checklist, caplog):
    secret_turn = "СЕКРЕТНАЯ_РЕПЛИКА_12345 Здравствуйте"
    d = make_dialog(("client", "вопрос"), ("operator", secret_turn))
    mock = MockClient([Fault("fake_quote", criterion_id="c01", calls=(1,))])
    with caplog.at_level(logging.DEBUG):
        out = evaluate(d, default_checklist, client=mock)
    text = caplog.text
    assert "evaluator_call" in text and "c01:quote_not_found" in text
    assert "СЕКРЕТНАЯ" not in text and "выдуманная" not in text and "вопрос" not in text
    quotes = [e.quote for r in out.results for e in r.evidence if e.quote]
    assert quotes and all(q not in text for q in quotes)


# --- конфигурация и Anthropic (без сети) ---


def test_make_client_env(monkeypatch):
    monkeypatch.delenv("CQA_EVALUATOR", raising=False)
    assert isinstance(make_client(), MockClient)  # mock по умолчанию, без ключа
    monkeypatch.setenv("CQA_EVALUATOR", "bogus")
    with pytest.raises(ValueError):
        make_client()
    monkeypatch.setenv("CQA_EVALUATOR", "llm")
    monkeypatch.delenv("CQA_LLM_MODEL", raising=False)
    with pytest.raises(ValueError):
        make_client()


def test_evaluate_defaults_to_mock_without_key(simple_dialog, default_checklist, monkeypatch):
    monkeypatch.setenv("CQA_EVALUATOR", "mock")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert evaluate(simple_dialog, default_checklist).usage.model == "mock"


class _FakeSDK:
    def __init__(self, tool_input, exc=None):
        self.kwargs, self.exc, self.tool_input = None, exc, tool_input
        self.messages = self

    def create(self, **kwargs):
        from types import SimpleNamespace as NS

        # Реальная сигнатура установленного SDK: неизвестный параметр падает здесь, как упал бы вживую.
        inspect.signature(anthropic.resources.messages.Messages.create).bind(None, **kwargs)

        if self.exc:
            raise self.exc
        self.kwargs = kwargs
        usage = NS(
            input_tokens=10, output_tokens=5, cache_creation_input_tokens=100, cache_read_input_tokens=None
        )
        block = NS(type="tool_use", name="submit_evaluation", input=self.tool_input)
        return NS(content=[block], usage=usage, model="m-1")


def test_anthropic_request_shape_and_usage():
    sdk = _FakeSDK({"c01": {}})
    client = AnthropicClient("m-1", sdk_client=sdk)
    resp = client.complete("SYS", "USR", {"type": "object"})
    k = sdk.kwargs
    assert "temperature" not in k and k["tool_choice"] == {"type": "tool", "name": "submit_evaluation"}
    assert k["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert (resp.input_tokens, resp.output_tokens, resp.tool_input) == (110, 5, {"c01": {}})


def test_anthropic_errors_mapped_without_leaking_body():
    exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    with pytest.raises(LLMUnavailableError) as ei:
        AnthropicClient("m", sdk_client=_FakeSDK(None, exc)).complete("s", "u", {})
    assert "APIConnectionError" in str(ei.value)


def test_fake_sdk_rejects_unsupported_kwargs():
    """Страховка теста выше: фейк действительно ловит параметры, которых нет в SDK."""
    with pytest.raises(TypeError):
        inspect.signature(anthropic.resources.messages.Messages.create).bind(None, temperature=0)


def test_anthropic_status_code_in_error_without_body():
    req = httpx.Request("POST", "https://x")
    resp = httpx.Response(429, request=req, text="СЕКРЕТНОЕ_ТЕЛО")
    exc = anthropic.RateLimitError("СЕКРЕТНОЕ_ТЕЛО", response=resp, body=None)
    with pytest.raises(LLMUnavailableError) as ei:
        AnthropicClient("m", sdk_client=_FakeSDK(None, exc)).complete("s", "u", {})
    assert ei.value.status_code == 429 and "429" in str(ei.value) and "СЕКРЕТНОЕ" not in str(ei.value)


def test_new_scale_criterion_end_to_end(simple_dialog, new_criterion_checklist):
    out = evaluate(simple_dialog, new_criterion_checklist, client=MockClient())
    x99 = out.results[-1]
    assert x99.criterion_id == "x99" and x99.answer == "scale" and x99.scale_value in range(6)


# --- логирование и Usage ---


def test_summary_log_on_success_has_usage_and_no_texts(simple_dialog, default_checklist, caplog):
    with caplog.at_level(logging.DEBUG):
        evaluate(simple_dialog, default_checklist, client=_Priced(), prices=Prices(2.0, 10.0))
    done = [r.getMessage() for r in caplog.records if "evaluator_done" in r.getMessage()]
    assert len(done) == 1
    assert "status=ok" in done[0] and "calls=2" in done[0] and "cost_usd=" in done[0]
    assert "Здравствуйте" not in caplog.text and "Откройте" not in caplog.text


def test_summary_log_on_validation_failure(simple_dialog, default_checklist, caplog):
    mock = MockClient([Fault("fake_quote", criterion_id="c01")])
    with caplog.at_level(logging.DEBUG), pytest.raises(ValidationFailedError) as ei:
        evaluate(simple_dialog, default_checklist, client=mock)
    done = [r.getMessage() for r in caplog.records if "evaluator_done" in r.getMessage()]
    assert len(done) == 1 and "status=failed" in done[0] and "calls=3" in done[0]
    assert "c01:quote_not_found" in done[0]
    assert "выдуманная" not in caplog.text and ei.value.usage.llm_calls == 3


def test_transport_error_keeps_spent_usage_and_logs(simple_dialog, default_checklist, caplog):
    class DownAfterOne:
        n = 0

        def complete(self, system, user, tool_schema):
            self.n += 1
            if self.n == 1:
                return LLMResponse(None, 700, 50, "test-model")
            raise LLMUnavailableError("HTTP 503", status_code=503)

    with caplog.at_level(logging.DEBUG), pytest.raises(LLMUnavailableError) as ei:
        evaluate(simple_dialog, default_checklist, client=DownAfterOne(), prices=Prices(2.0, 10.0))
    u = ei.value.usage
    assert (u.llm_calls, u.input_tokens, u.output_tokens, u.model) == (1, 700, 50, "test-model")
    done = [r.getMessage() for r in caplog.records if "evaluator_done" in r.getMessage()]
    assert len(done) == 1 and "status=llm_unavailable" in done[0] and "status_code=503" in done[0]
