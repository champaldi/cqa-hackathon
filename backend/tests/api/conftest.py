"""Приложение на заглушках для тестов API: без сети, без ключей и без .env."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.settings import Settings


class Api:
    """Проверяет конверт ответа и возвращает поле data."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, path: str, status: int = 200, **kwargs: Any) -> Any:
        return self._data(self.client.get(path, **kwargs), status)

    def post(self, path: str, json: Any = None, status: int = 200) -> Any:
        return self._data(self.client.post(path, json=json), status)

    def error(self, method: str, path: str, status: int, json: Any = None) -> str:
        response = self.client.request(method, path, json=json)
        assert response.status_code == status, response.text
        body = response.json()
        assert body["success"] is False
        assert body["data"] is None
        return body["error"]

    @staticmethod
    def _data(response: httpx.Response, status: int) -> Any:
        assert response.status_code == status, response.text
        body = response.json()
        assert body["success"] is True
        assert body["error"] is None
        return body["data"]

    def evaluate(self, conversation_id: str = "sample-ru-001", checklist_id: str | None = None) -> dict:
        payload = {"conversation_id": conversation_id, "checklist_id": checklist_id}
        return self.post("/api/evaluations", payload)


@pytest.fixture
def api() -> Iterator[Api]:
    with TestClient(create_app(Settings())) as client:
        yield Api(client)
