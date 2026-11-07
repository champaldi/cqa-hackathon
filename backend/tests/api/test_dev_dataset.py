"""Проверки на настоящем наборе DEV из API организаторов: 65 диалогов.

Файла data/dev.json нет в git, поэтому в CI эти тесты пропускаются. Локально он
получается запросом к API, см. README. Содержимое диалогов в вывод не попадает.
"""

import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import services as services_module
from backend.app.contracts import Dialog
from backend.app.datasets.normalize import normalize_dataset
from backend.app.main import create_app
from backend.app.settings import Settings

DEV_PATH = Path(__file__).parents[3] / "data" / "dev.json"

pytestmark = pytest.mark.skipif(not DEV_PATH.exists(), reason="data/dev.json есть только локально")


@pytest.fixture(scope="module")
def payload() -> dict:
    response = json.loads(DEV_PATH.read_text(encoding="utf-8"))
    assert response["isSuccess"] is True
    return response["data"]


@pytest.fixture(scope="module")
def dialogs(payload: dict) -> list[Dialog]:
    return normalize_dataset(payload)


@pytest.fixture
def client(payload: dict, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(services_module, "fetch_group", lambda url, group_id: payload)
    with TestClient(create_app(Settings(dataset_url="https://organizers.test"))) as test_client:
        yield test_client


def run_batch(client: TestClient) -> dict:
    client.post("/api/dialogs/import", json={"group_id": "DEV"})
    job = client.post("/api/batches", json={"group_id": "DEV"}).json()["data"]
    return client.get(f"/api/batches/{job['id']}").json()["data"]


def test_every_record_is_normalized(dialogs: list[Dialog], payload: dict) -> None:
    assert len(dialogs) == payload["total_records"] == 65


def test_set_matches_the_organizers_description(dialogs: list[Dialog]) -> None:
    assert Counter(d.channel for d in dialogs) == {"agent chat": 60, "voice call": 5}
    assert Counter(d.language for d in dialogs) == {"RU": 35, "KZ": 15, "EN": 15}


def test_only_calls_have_a_recording(dialogs: list[Dialog]) -> None:
    assert all(bool(d.audio_url) == (d.channel == "voice call") for d in dialogs)


def test_source_timestamps_stay_unchanged(dialogs: list[Dialog], payload: dict) -> None:
    for dialog, record in zip(dialogs, payload["records"], strict=True):
        assert [t.timestamp for t in dialog.transcript] == [t["timestamp"] for t in record["transcript"]]


def test_import_brings_the_whole_group(client: TestClient) -> None:
    response = client.post("/api/dialogs/import", json={"group_id": "DEV"})

    assert response.json()["data"] == {"group_id": "DEV", "imported": 65}


def test_batch_evaluates_every_dialog_without_failures(client: TestClient) -> None:
    finished = run_batch(client)

    assert (finished["status"], finished["done"], finished["failed"]) == ("done", 65, 0)


def test_every_card_opens_with_all_criteria(client: TestClient) -> None:
    run_batch(client)

    summaries = client.get("/api/dialogs", params={"group_id": "DEV"}).json()["data"]
    cards = [client.get(f"/api/evaluations/{s['evaluation_id']}").json()["data"] for s in summaries]

    assert len(cards) == 65
    assert all(len(card["final_results"]) == 8 for card in cards)
