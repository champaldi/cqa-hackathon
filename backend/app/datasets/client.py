"""Запрос к API организаторов.

Ссылка подписана (sig), поэтому её нет в тексте ошибок и в цепочке исключений.
Повторы и локальный кеш добавляет задача backend/data-and-storage.
"""

import logging
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from backend.app.errors import DatasetError

TIMEOUT_SEC = 30.0

# На уровне INFO эти логгеры пишут адрес запроса целиком, вместе с подписью sig.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def with_group_id(url: str, group_id: str) -> str:
    """Меняет только group_id: остальные параметры подписи остаются байт в байт."""
    parts = urlsplit(url)
    param = urlencode({"group_id": group_id})
    pairs = [pair for pair in parts.query.split("&") if pair]
    replaced = [param if pair.startswith("group_id=") else pair for pair in pairs]
    if param not in replaced:
        replaced.append(param)
    return urlunsplit(parts._replace(query="&".join(replaced)))


def fetch_group(
    url: str, group_id: str, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    """Возвращает раздел data из ответа API."""
    try:
        with httpx.Client(timeout=TIMEOUT_SEC, transport=transport) as client:
            response = client.get(with_group_id(url, group_id))
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise DatasetError(f"API организаторов ответил {exc.response.status_code}") from None
    except (httpx.HTTPError, ValueError) as exc:
        raise DatasetError(f"API организаторов недоступен: {type(exc).__name__}") from None
    return _unwrap(payload)


def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DatasetError("API организаторов вернул неожиданный ответ")
    if not payload.get("isSuccess"):
        raise DatasetError(f"API организаторов вернул ошибку: {payload.get('error') or 'без описания'}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise DatasetError("В ответе API организаторов нет раздела data")
    return data
