import logging
import threading

import pytest

from backend.app.evaluator import (
    EvaluationError,
    LlmEvaluator,
    LLMRejectedError,
    LLMUnavailableError,
    NoOperatorTurnsError,
    ValidationFailedError,
    build_llm_evaluator,
    evaluate,
)
from backend.app.evaluator.client import Fault, LLMResponse, MockClient, Prices

from .conftest import make_dialog

MODEL = "test-model"


def run(dialog, checklist, client, **kw):
    return evaluate(dialog, checklist, client=client, model=MODEL, **kw)


def done_lines(caplog):
    return [r for r in caplog.records if "evaluator_done" in r.getMessage()]


def test_mock_happy_path(simple_dialog, default_checklist):
    out = run(simple_dialog, default_checklist, MockClient(default_checklist))
    assert [r.criterion_id for r in out.results] == [c.id for c in default_checklist.criteria]
    assert out.usage.model == MODEL and out.usage.llm_calls == 1  # имя модели, а не mock
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cost_usd) == (0, 0, 0)
    for r in out.results:
        for e in r.evidence:
            if e.kind == "quote":
                assert e.quote in simple_dialog.transcript[e.turn_index].text


def test_all_samples_pass_through_mock(fake_dialogs, default_checklist):
    assert len(fake_dialogs) == 4
    for d in fake_dialogs:
        out = run(d, default_checklist, MockClient(default_checklist))
        assert len(out.results) == len(default_checklist.criteria), d.conversation_id


def test_mock_na_path_kz_sample(fake_dialogs, default_checklist):
    kz = next(d for d in fake_dialogs if d.conversation_id == "sample-kz-001")
    out = run(kz, default_checklist, MockClient(default_checklist, na_criteria=frozenset({"c07"})))
    c07 = next(r for r in out.results if r.criterion_id == "c07")
    assert c07.answer == "na" and c07.evidence[0].kind == "na_reason"


def test_new_scale_criterion_end_to_end(simple_dialog, new_criterion_checklist):
    out = run(simple_dialog, new_criterion_checklist, MockClient(new_criterion_checklist))
    x99 = out.results[-1]
    assert x99.criterion_id == "x99" and x99.answer == "scale" and x99.scale_value in range(6)


def test_client_is_required_no_hidden_mock(simple_dialog, default_checklist):
    with pytest.raises(TypeError):
        evaluate(simple_dialog, default_checklist, model=MODEL)  # type: ignore[call-arg]


# --- retry ---


@pytest.mark.parametrize(
    "kind", ["bad_scale_step", "fake_quote", "illegal_na", "missing_criterion", "duplicate_criterion"]
)
def test_criterion_fault_repaired_only_for_that_criterion(simple_dialog, default_checklist, kind):
    mock = MockClient(default_checklist, [Fault(kind, calls=(1,))])
    out = run(simple_dialog, default_checklist, mock)
    assert out.usage.llm_calls == 2 and len(out.results) == len(default_checklist.criteria)
    assert len(mock.requested[1]) == 1


@pytest.mark.parametrize("kind", ["bad_json", "max_tokens", "refusal"])
def test_whole_reply_fault_retried_for_all(simple_dialog, default_checklist, kind):
    mock = MockClient(default_checklist, [Fault(kind, calls=(1,))])
    out = run(simple_dialog, default_checklist, mock)
    assert out.usage.llm_calls == 2 and mock.requested[1] == mock.requested[0]


def test_unknown_criterion_id_triggers_retry_and_fails_when_persistent(simple_dialog, default_checklist):
    class UnknownId:
        def __init__(self, inner):
            self.inner, self.n = inner, 0

        def complete(self, system, user, schema):
            import json

            self.n += 1
            reply = self.inner.complete(system, user, schema)
            data = json.loads(reply.text)
            data["results"].append({**data["results"][0], "criterion_id": "zzz_unknown"})
            return LLMResponse(json.dumps(data, ensure_ascii=False), 0, 0, "end_turn")

    client = UnknownId(MockClient(default_checklist))
    with pytest.raises(ValidationFailedError) as ei:
        run(simple_dialog, default_checklist, client)
    assert client.n == 3 and {e.code for e in ei.value.errors} == {"unknown_criterion"}


def test_specific_criterion_requested_again(simple_dialog, default_checklist):
    mock = MockClient(default_checklist, [Fault("bad_scale_step", criterion_id="c06", calls=(1,))])
    run(simple_dialog, default_checklist, mock)
    assert mock.requested[1] == ["c06"]


class _Recording:
    def __init__(self, inner):
        self.inner, self.schemas, self.systems = inner, [], []

    def complete(self, system, user, schema):
        self.schemas.append(schema)
        self.systems.append(system)
        return self.inner.complete(system, user, schema)


def test_schema_and_system_unchanged_between_attempts(simple_dialog, default_checklist):
    rec = _Recording(MockClient(default_checklist, [Fault("fake_quote", criterion_id="c01")]))
    with pytest.raises(ValidationFailedError):
        run(simple_dialog, default_checklist, rec)
    assert len(rec.schemas) == 3 and rec.schemas[0] == rec.schemas[1] == rec.schemas[2]
    assert len(set(rec.systems)) == 1  # кеш не сбрасывается


def test_persistent_fault_fails_after_two_repair_rounds(simple_dialog, default_checklist):
    mock = MockClient(default_checklist, [Fault("fake_quote", criterion_id="c01")])
    with pytest.raises(ValidationFailedError) as ei:
        run(simple_dialog, default_checklist, mock, prices=Prices(1.0, 1.0))
    assert mock.calls == 3 and mock.requested[1:] == [["c01"], ["c01"]]
    assert ei.value.usage.llm_calls == 3 and ei.value.status_code == 502 and not ei.value.retryable
    assert [e.criterion_id for e in ei.value.errors] == ["c01"]
    assert isinstance(ei.value, EvaluationError)


def test_repair_round_limit_is_configurable(simple_dialog, default_checklist):
    mock = MockClient(default_checklist, [Fault("bad_json")])
    with pytest.raises(ValidationFailedError):
        run(simple_dialog, default_checklist, mock, max_repair_rounds=0)
    assert mock.calls == 1


def test_final_merge_guard_rejects_missing_or_duplicate(simple_dialog, default_checklist, monkeypatch):
    from backend.app.evaluator import core

    real = core.validate_complete
    monkeypatch.setattr(core, "validate_complete", lambda r, cl, t: real(r[:-1], cl, t))
    with pytest.raises(ValidationFailedError) as ei:
        run(simple_dialog, default_checklist, MockClient(default_checklist))
    assert {e.code for e in ei.value.errors} == {"missing"}
    monkeypatch.setattr(core, "validate_complete", lambda r, cl, t: real([*r, r[0]], cl, t))
    with pytest.raises(ValidationFailedError) as ei:
        run(simple_dialog, default_checklist, MockClient(default_checklist))
    assert {e.code for e in ei.value.errors} == {"duplicate"}


# --- прекек, usage, ошибки ---


@pytest.mark.parametrize("speakers", [["client", "bot", "system"], []])
def test_no_operator_turns_zero_calls(default_checklist, speakers):
    d = make_dialog(*[(s, "текст") for s in speakers])
    mock = MockClient(default_checklist)
    with pytest.raises(NoOperatorTurnsError) as ei:
        run(d, default_checklist, mock)
    assert mock.calls == 0 and ei.value.status_code == 422 and not ei.value.retryable
    assert ei.value.usage.llm_calls == 0 and ei.value.usage.model == MODEL


class _Scripted:
    """Клиент с заранее заданными ответами. Без валидного ответа возвращает JSON от mock."""

    def __init__(self, checklist, replies):
        self.mock, self.replies, self.n = MockClient(checklist), list(replies), 0

    def complete(self, system, user, schema):
        self.n += 1
        if self.n <= len(self.replies):
            r = self.replies[self.n - 1]
            if isinstance(r, Exception):
                raise r
            return r
        inner = self.mock.complete(system, user, schema)
        return LLMResponse(inner.text, 1_000_000, 500_000, "end_turn")


def test_usage_sums_all_calls_including_rejected(simple_dialog, default_checklist):
    bad = LLMResponse("не json", 3000, 1500, "end_turn")
    out = run(simple_dialog, default_checklist, _Scripted(default_checklist, [bad]), prices=Prices(3.0, 15.0))
    u = out.usage
    assert (u.llm_calls, u.input_tokens, u.output_tokens) == (2, 1_003_000, 501_500)
    assert u.cost_usd == pytest.approx(1_003_000 * 3 / 1e6 + 501_500 * 15 / 1e6)


def test_cost_formula(simple_dialog, default_checklist):
    ok = MockClient(default_checklist).complete("", "", {})
    reply = LLMResponse(ok.text, 3000, 1500, "end_turn")
    out = run(
        simple_dialog, default_checklist, _Scripted(default_checklist, [reply]), prices=Prices(2.0, 10.0)
    )
    assert out.usage.cost_usd == pytest.approx(0.021)


def test_max_tokens_goes_to_retry_and_usage(simple_dialog, default_checklist):
    cut = LLMResponse('{"results": [', 100, 8192, "max_tokens")
    out = run(simple_dialog, default_checklist, _Scripted(default_checklist, [cut]))
    assert out.usage.llm_calls == 2 and out.usage.output_tokens == 8192 + 500_000


def test_unavailable_propagates_with_spent_usage_and_log(simple_dialog, default_checklist, caplog):
    down = LLMUnavailableError("HTTP 503", upstream_status=503)
    first = LLMResponse("не json", 700, 50, "end_turn")
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMUnavailableError) as ei:
        run(
            simple_dialog,
            default_checklist,
            _Scripted(default_checklist, [first, down]),
            prices=Prices(2.0, 10.0),
        )
    u = ei.value.usage
    assert (u.llm_calls, u.input_tokens, u.output_tokens, u.model) == (1, 700, 50, MODEL)
    assert ei.value.status_code == 503 and ei.value.retryable and ei.value.upstream_status == 503
    lines = done_lines(caplog)
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    assert "llm_calls=1" in lines[0].getMessage() and "input_tokens=700" in lines[0].getMessage()


def test_rejected_error_not_retryable_and_keeps_usage(simple_dialog, default_checklist):
    first = LLMResponse("не json", 10, 5, "end_turn")
    err = LLMRejectedError("HTTP 400", upstream_status=400)
    with pytest.raises(LLMRejectedError) as ei:
        run(simple_dialog, default_checklist, _Scripted(default_checklist, [first, err]))
    assert ei.value.status_code == 502 and not ei.value.retryable and ei.value.usage.llm_calls == 1
    assert ei.value.upstream_status == 400 and "400" in str(ei.value)


def test_error_hierarchy_status_codees():
    statuses = {
        NoOperatorTurnsError: (422, False),
        ValidationFailedError: (502, False),
        LLMUnavailableError: (503, True),
        LLMRejectedError: (502, False),
    }
    for cls, (status, retry) in statuses.items():
        assert issubclass(cls, EvaluationError) and cls.status_code == status and cls.retryable is retry


# --- логи ---


def test_logs_do_not_contain_texts_and_failure_is_one_warning(default_checklist, caplog):
    d = make_dialog(("client", "вопрос"), ("operator", "СЕКРЕТНАЯ_РЕПЛИКА_12345 Здравствуйте"))
    mock = MockClient(default_checklist, [Fault("fake_quote", criterion_id="c01")])
    with caplog.at_level(logging.DEBUG), pytest.raises(ValidationFailedError):
        run(d, default_checklist, mock, prices=Prices(1.0, 1.0))
    lines = done_lines(caplog)
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    msg = lines[0].getMessage()
    for key in (
        "llm_calls=3",
        "input_tokens=0",
        "output_tokens=0",
        "cost_usd=0.000000",
        "c01:quote_not_found",
    ):
        assert key in msg
    assert "СЕКРЕТНАЯ" not in caplog.text and "выдуманная" not in caplog.text and "вопрос" not in caplog.text


def test_success_log_has_usage_and_no_texts(simple_dialog, default_checklist, caplog):
    with caplog.at_level(logging.DEBUG):
        out = run(simple_dialog, default_checklist, MockClient(default_checklist))
    assert len(done_lines(caplog)) == 1 and done_lines(caplog)[0].levelno == logging.INFO
    quotes = [e.quote for r in out.results for e in r.evidence if e.quote]
    assert quotes and all(q not in caplog.text for q in quotes)


# --- LlmEvaluator, factory, потоки ---


def test_llm_evaluator_object_interface(simple_dialog, default_checklist):
    ev = LlmEvaluator(MockClient(default_checklist), model=MODEL, prices=Prices(2.0, 10.0))
    out = ev.evaluate(simple_dialog, default_checklist)
    assert out.usage.model == MODEL and len(out.results) == len(default_checklist.criteria)


def test_factory_builds_evaluator_without_network_and_never_falls_back():
    ev = build_llm_evaluator(api_key="k", model="m", price_input_per_mtok=1, price_output_per_mtok=2)
    assert isinstance(ev, LlmEvaluator)
    for bad in ({"api_key": "", "model": "m"}, {"api_key": "k", "model": ""}):
        with pytest.raises(ValueError):
            build_llm_evaluator(price_input_per_mtok=1, price_output_per_mtok=2, **bad)


def test_evaluate_is_thread_safe(simple_dialog, default_checklist):
    ev = LlmEvaluator(MockClient(default_checklist), model=MODEL, prices=Prices())
    results, errors = [], []

    def work():
        try:
            results.append(ev.evaluate(simple_dialog, default_checklist))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(results) == 8 and all(r.usage.llm_calls == 1 for r in results)
