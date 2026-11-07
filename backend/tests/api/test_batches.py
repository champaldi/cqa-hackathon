from fastapi.testclient import TestClient

from backend.app.contracts import Checklist, Dialog, EvaluatorOutput
from backend.app.evaluator.mock import MockEvaluator
from backend.app.main import create_app
from backend.app.settings import Settings


class FailsOnOneDialog:
    def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
        if dialog.conversation_id == "sample-kz-001":
            raise RuntimeError("модель не ответила")
        return MockEvaluator().evaluate(dialog, checklist)


def test_batch_evaluates_the_whole_group(api) -> None:
    job = api.post("/api/batches", {"group_id": "SAMPLE"}, status=202)

    finished = api.get(f"/api/batches/{job['id']}")

    assert finished["status"] == "done"
    assert finished["done"] == finished["total"] == 4
    assert all(d["evaluation_id"] for d in api.get("/api/dialogs"))


def test_batch_of_unknown_group_is_404(api) -> None:
    assert api.error("POST", "/api/batches", 404, json={"group_id": "UNKNOWN"})


def test_batch_with_unknown_checklist_is_404(api) -> None:
    payload = {"group_id": "SAMPLE", "checklist_id": "unknown"}

    assert api.error("POST", "/api/batches", 404, json=payload)


def test_missing_batch_is_404(api) -> None:
    assert api.error("GET", "/api/batches/unknown", 404)


def test_failed_dialog_does_not_stop_the_batch() -> None:
    with TestClient(create_app(Settings(), evaluator=FailsOnOneDialog())) as client:
        job = client.post("/api/batches", json={"group_id": "SAMPLE"}).json()["data"]
        finished = client.get(f"/api/batches/{job['id']}").json()["data"]

    assert finished["status"] == "done"
    assert finished["done"] == 3
    assert finished["failed"] == 1
    assert "sample-kz-001" in finished["errors"][0]
