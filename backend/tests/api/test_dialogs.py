from fastapi.testclient import TestClient

from backend.app import services as services_module
from backend.app.errors import DatasetError
from backend.app.main import create_app
from backend.app.settings import Settings

RAW_GROUP = {
    "dataset_group_id": "CONTROL",
    "records": [
        {
            "conversation_id": "control-001",
            "channel": "agent chat",
            "language": "RU",
            "transcript": [{"timestamp": "00:00", "speaker": "operator", "text": "Здравствуйте"}],
            "audio_url": None,
        }
    ],
}


def test_sample_dialogs_are_available_on_start(api) -> None:
    dialogs = api.get("/api/dialogs")

    assert {d["language"] for d in dialogs} == {"RU", "KZ", "EN"}
    assert all(d["evaluation_id"] is None for d in dialogs)


def test_dialogs_can_be_filtered_by_group(api) -> None:
    assert api.get("/api/dialogs", params={"group_id": "NONE"}) == []


def test_dialog_keeps_its_transcript(api) -> None:
    dialog = api.get("/api/dialogs/sample-ru-001")

    assert dialog["transcript"][0]["timestamp"] == "00:00"
    assert dialog["transcript"][0]["index"] == 0


def test_missing_dialog_is_404(api) -> None:
    assert "unknown" in api.error("GET", "/api/dialogs/unknown", 404)


def test_summary_shows_the_latest_evaluation(api) -> None:
    card = api.evaluate()

    summary = next(d for d in api.get("/api/dialogs") if d["conversation_id"] == "sample-ru-001")

    assert summary["evaluation_id"] == card["evaluation"]["id"]
    assert summary["total"] == card["final_score"]["total"]


def test_import_without_dataset_url_explains_what_to_do(api) -> None:
    assert "CQA_DATASET_URL" in api.error("POST", "/api/dialogs/import", 503, json={"group_id": "DEV"})


def test_import_rejects_unsafe_group_id(api) -> None:
    assert api.error("POST", "/api/dialogs/import", 422, json={"group_id": "DEV&sig=x"})


def test_import_adds_dialogs_of_the_group(monkeypatch) -> None:
    monkeypatch.setattr(services_module, "fetch_group", lambda url, group_id: RAW_GROUP)

    with TestClient(create_app(Settings(dataset_url="https://organizers.test"))) as client:
        imported = client.post("/api/dialogs/import", json={"group_id": "CONTROL"}).json()["data"]
        listed = client.get("/api/dialogs", params={"group_id": "CONTROL"}).json()["data"]

    assert imported == {"group_id": "CONTROL", "imported": 1}
    assert [d["conversation_id"] for d in listed] == ["control-001"]


def test_import_refuses_a_different_group_than_requested(monkeypatch) -> None:
    monkeypatch.setattr(services_module, "fetch_group", lambda url, group_id: RAW_GROUP)

    with TestClient(create_app(Settings(dataset_url="https://organizers.test"))) as client:
        response = client.post("/api/dialogs/import", json={"group_id": "DEV"})
        listed = client.get("/api/dialogs", params={"group_id": "CONTROL"}).json()["data"]

    assert response.status_code == 502
    assert "CONTROL" in response.json()["error"]
    assert listed == []


def test_import_failure_is_reported_as_bad_gateway(monkeypatch) -> None:
    def fail(url: str, group_id: str) -> dict:
        raise DatasetError("API организаторов ответил 403")

    monkeypatch.setattr(services_module, "fetch_group", fail)

    with TestClient(create_app(Settings(dataset_url="https://organizers.test"))) as client:
        response = client.post("/api/dialogs/import", json={"group_id": "DEV"})

    assert response.status_code == 502
    assert response.json()["error"] == "API организаторов ответил 403"
