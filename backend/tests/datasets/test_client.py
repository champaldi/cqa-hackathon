import httpx
import pytest

from backend.app.datasets.client import fetch_group
from backend.app.errors import DatasetError

SIGNED_URL = "https://organizers.test/api?group_id=DEV&sig=top-secret"
DATA = {"dataset_group_id": "DEV", "total_records": 0, "records": []}


def respond_with(status: int = 200, **body: object) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _request: httpx.Response(status, json=body))


def test_returns_data_section_of_the_envelope() -> None:
    transport = respond_with(error="", isSuccess=True, data=DATA)

    assert fetch_group(SIGNED_URL, "DEV", transport=transport) == DATA


def test_group_id_replaces_value_in_signed_url() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"error": "", "isSuccess": True, "data": DATA})

    fetch_group(SIGNED_URL, "CONTROL", transport=httpx.MockTransport(handler))

    assert seen[0].params["group_id"] == "CONTROL"
    assert seen[0].params["sig"] == "top-secret"


def test_organizers_error_is_passed_to_the_user() -> None:
    transport = respond_with(error="group not found", isSuccess=False, data=None)

    with pytest.raises(DatasetError, match="group not found"):
        fetch_group(SIGNED_URL, "DEV", transport=transport)


def test_http_error_does_not_reveal_signed_url() -> None:
    with pytest.raises(DatasetError) as caught:
        fetch_group(SIGNED_URL, "DEV", transport=respond_with(status=403))

    assert "403" in str(caught.value)
    assert "top-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_network_error_does_not_reveal_signed_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(DatasetError) as caught:
        fetch_group(SIGNED_URL, "DEV", transport=httpx.MockTransport(handler))

    assert "top-secret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_answer_that_is_not_json_is_an_error() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="<html>"))

    with pytest.raises(DatasetError):
        fetch_group(SIGNED_URL, "DEV", transport=transport)


def test_answer_without_data_section_is_an_error() -> None:
    with pytest.raises(DatasetError):
        fetch_group(SIGNED_URL, "DEV", transport=respond_with(isSuccess=True, data=None))
