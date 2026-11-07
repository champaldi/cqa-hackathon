"""LlmEvaluator и ошибки evaluator в приложении: create_app, маршруты, пакетная оценка."""

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts import Checklist, Dialog, EvaluatorOutput, Turn
from backend.app.errors import AppError
from backend.app.evaluator import (
    EvaluationError,
    LlmEvaluator,
    LLMRejectedError,
    LLMUnavailableError,
    NoOperatorTurnsError,
    ValidationFailedError,
)
from backend.app.evaluator.base import Evaluator
from backend.app.evaluator.client import MockClient, Prices
from backend.app.evaluator.errors import CriterionError
from backend.app.main import create_app
from backend.app.settings import Settings

SECRET = "СЕКРЕТНЫЙ_ТЕКСТ_РЕПЛИКИ"


def llm_evaluator(default_checklist: Checklist, **kw) -> LlmEvaluator:
    client = MockClient(default_checklist, **kw)
    return LlmEvaluator(client, model="test-model", prices=Prices(2.0, 10.0))


def test_llm_evaluator_works_through_the_backend_protocol(
    default_checklist: Checklist, fake_dialogs: list[Dialog]
) -> None:
    """Вызов ровно так, как зовёт Services: evaluate(dialog, checklist) -> EvaluatorOutput."""
    evaluator: Evaluator = llm_evaluator(default_checklist)
    for dialog in fake_dialogs:
        output = evaluator.evaluate(dialog, default_checklist)
        assert isinstance(output, EvaluatorOutput)
        assert [r.criterion_id for r in output.results] == [c.id for c in default_checklist.criteria]
        assert output.usage.model == "test-model" and output.usage.llm_calls == 1
        for result in output.results:
            if result.answer == "scale":
                criterion = next(c for c in default_checklist.criteria if c.id == result.criterion_id)
                assert result.scale_value in {step.value for step in criterion.scale or []}
            assert result.explanation and result.evidence


def test_evaluation_route_with_llm_evaluator(default_checklist: Checklist) -> None:
    with TestClient(create_app(Settings(), evaluator=llm_evaluator(default_checklist))) as client:
        body = client.post("/api/evaluations", json={"conversation_id": "sample-ru-001"}).json()
        assert body["success"] is True
        card = body["data"]
        assert card["evaluation"]["usage"]["model"] == "test-model"  # не mock
        assert card["evaluation"]["usage"]["llm_calls"] == 1
        assert len(card["evaluation"]["results"]) == len(default_checklist.criteria)
        assert card["final_score"]["total"] is not None
        summary = client.get("/api/dialogs").json()["data"]
        assert any(d["evaluation_id"] for d in summary)


def test_whole_sample_group_passes_through_llm_evaluator_and_scoring(default_checklist: Checklist) -> None:
    with TestClient(create_app(Settings(), evaluator=llm_evaluator(default_checklist))) as client:
        job = client.post("/api/batches", json={"group_id": "SAMPLE"}).json()["data"]
        done = client.get(f"/api/batches/{job['id']}").json()["data"]
    assert (done["status"], done["done"], done["failed"]) == ("done", 4, 0)


class Raises:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (NoOperatorTurnsError("sample-ru-001"), 422),
        (ValidationFailedError([CriterionError("c01", "quote_not_found", "m")]), 502),
        (LLMUnavailableError("вызов модели не удался: RateLimitError, HTTP 429", upstream_status=429), 503),
        (LLMRejectedError("вызов модели не удался: AuthenticationError, HTTP 401", upstream_status=401), 502),
    ],
)
def test_evaluator_errors_map_to_http_statuses_in_the_envelope(exc: EvaluationError, status: int) -> None:
    with TestClient(create_app(Settings(), evaluator=Raises(exc))) as client:
        response = client.post("/api/evaluations", json={"conversation_id": "sample-ru-001"})
    assert response.status_code == status and isinstance(exc, AppError)
    body = response.json()
    assert body["success"] is False and body["data"] is None and body["error"] == str(exc)


def test_batch_survives_every_evaluator_error_and_counts_failures() -> None:
    errors = [
        NoOperatorTurnsError("x"),
        ValidationFailedError([]),
        LLMUnavailableError("down", upstream_status=503),
        LLMRejectedError("bad", upstream_status=400),
    ]

    class EachDialogFails:
        def __init__(self) -> None:
            self.n = 0

        def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
            self.n += 1
            raise errors[self.n - 1]

    with TestClient(create_app(Settings(), evaluator=EachDialogFails())) as client:
        job = client.post("/api/batches", json={"group_id": "SAMPLE"}).json()["data"]
        done = client.get(f"/api/batches/{job['id']}").json()["data"]
    assert (done["status"], done["done"], done["failed"]) == ("done", 0, 4)
    assert all(SECRET not in e for e in done["errors"])


def test_error_text_shown_to_user_has_no_dialog_text(default_checklist: Checklist) -> None:
    dialog = Dialog(
        conversation_id="secret-dialog",
        dataset_group_id="T",
        channel="agent chat",
        language="RU",
        transcript=[Turn(index=0, timestamp="00:00", speaker="client", text=SECRET)],
    )
    with pytest.raises(NoOperatorTurnsError) as caught:
        llm_evaluator(default_checklist).evaluate(dialog, default_checklist)
    exc = caught.value
    assert SECRET not in str(exc) and "secret-dialog" in str(exc)
    assert exc.usage is not None and (exc.usage.llm_calls, exc.usage.input_tokens) == (0, 0)
    assert exc.usage.model == "test-model"


def test_mock_mode_unchanged_and_labelled_mock() -> None:
    """Режим mock не затронут: заглушка каркаса, детерминированная, без вызовов модели и затрат."""
    with TestClient(create_app(Settings(evaluator="mock"))) as client:
        assert client.get("/api/health").json()["data"]["evaluator"] == "mock"
        cards = [
            client.post("/api/evaluations", json={"conversation_id": "sample-kz-001"}).json()["data"]
            for _ in range(2)
        ]
    first, second = (c["evaluation"] for c in cards)
    assert first["usage"] == {
        "model": "mock",
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    }
    assert first["results"] == second["results"] and first["results"]
    assert cards[0]["final_score"] == cards[1]["final_score"]


def test_llm_mode_without_key_fails_create_app() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        create_app(Settings(evaluator="llm"))
