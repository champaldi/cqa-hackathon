"""Путь целиком: настоящий оценщик за интерфейсом каркаса. Модель подменена, сети и ключа нет."""

from typing import Any

import httpx
from fastapi.testclient import TestClient

from backend.app.contracts import Checklist
from backend.app.evaluator.client import Fault, LLMClient, LLMResponse, MockClient, Prices
from backend.app.evaluator.core import LlmEvaluator
from backend.app.evaluator.errors import LLMUnavailableError, NoOperatorTurnsError
from backend.app.main import create_app
from backend.app.settings import Settings


class DownClient:
    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        raise LLMUnavailableError("вызов модели не удался", upstream_status=429)


def post_evaluation(client: LLMClient) -> httpx.Response:
    app = create_app(Settings(), evaluator=LlmEvaluator(client, model="test-model", prices=Prices()))
    with TestClient(app, raise_server_exceptions=False) as http:
        return http.post("/api/evaluations", json={"conversation_id": "sample-ru-001"})


def test_evaluation_passes_through_the_app(default_checklist: Checklist) -> None:
    response = post_evaluation(MockClient(default_checklist))

    assert response.status_code == 200, response.text
    evaluation = response.json()["data"]["evaluation"]
    assert evaluation["results"]
    assert evaluation["usage"]["llm_calls"] == 1


def test_invalid_model_answer_is_502_in_the_envelope(default_checklist: Checklist) -> None:
    response = post_evaluation(MockClient(default_checklist, [Fault("fake_quote", criterion_id="c01")]))

    assert response.status_code == 502, response.text
    body = response.json()
    assert body["success"] is False
    assert "валидация не пройдена" in body["error"]


def test_unavailable_model_is_503_and_not_the_upstream_status() -> None:
    response = post_evaluation(DownClient())

    assert response.status_code == 503, response.text
    assert "вызов модели не удался" in response.json()["error"]


def test_dialog_without_operator_is_not_a_model_failure() -> None:
    assert NoOperatorTurnsError("x").status_code == 422
