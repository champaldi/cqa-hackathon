from fastapi.testclient import TestClient

from backend.app.contracts import Checklist, Dialog, EvaluatorOutput
from backend.app.main import create_app
from backend.app.settings import Settings


class BrokenEvaluator:
    def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
        raise RuntimeError("внутренняя подробность")


def test_health_shows_the_active_evaluator(api) -> None:
    assert api.get("/api/health")["evaluator"] == "mock"


def test_frontend_is_served_from_the_root(api) -> None:
    response = api.client.get("/")

    assert response.status_code == 200
    assert 'id="cqa-app"' in response.text


def test_shared_api_module_is_served(api) -> None:
    assert api.client.get("/api.js").status_code == 200


def test_unknown_api_route_uses_the_error_envelope(api) -> None:
    assert api.error("GET", "/api/unknown", 404)


def test_invalid_body_uses_the_error_envelope(api) -> None:
    assert "conversation_id" in api.error("POST", "/api/evaluations", 422, json={})


def test_unexpected_failure_hides_internal_details() -> None:
    app = create_app(Settings(), evaluator=BrokenEvaluator())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/evaluations", json={"conversation_id": "sample-ru-001"})

    assert response.status_code == 500
    assert response.json()["success"] is False
    assert "внутренняя подробность" not in response.text
