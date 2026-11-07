"""Запросы к внешним серверам: API организаторов и записи звонков.

Адреса подписаны (sig), поэтому их нет в логах, в тексте ошибок и в цепочке исключений.
Временные сбои повторяются. Локальная копия наборов лежит в cache.py.
"""

import logging
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from backend.app.errors import DatasetError

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 30.0
RETRY_DELAYS_SEC = (0.5, 1.5)
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

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


def _get_with_retries(
    client: httpx.Client, url: str, source: str, headers: Mapping[str, str] | None
) -> httpx.Response:
    for delay in RETRY_DELAYS_SEC:
        try:
            response = client.get(url, headers=headers)
        except httpx.TransportError as exc:
            reason = type(exc).__name__
        else:
            if response.status_code not in RETRY_STATUSES:
                return response
            reason = str(response.status_code)
        logger.warning("%s: сбой %s, повтор через %s с", source, reason, delay)
        time.sleep(delay)
    return client.get(url, headers=headers)


def get_checked(
    url: str,
    source: str,
    transport: httpx.BaseTransport | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """GET с повторами. В тексте ошибки только source, адрес туда не попадает."""
    try:
        with httpx.Client(timeout=TIMEOUT_SEC, transport=transport) as client:
            response = _get_with_retries(client, url, source, headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise DatasetError(f"{source} ответил {exc.response.status_code}") from None
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise DatasetError(f"{source} недоступен: {type(exc).__name__}") from None
    return response


def fetch_group(
    url: str, group_id: str, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    """Возвращает раздел data из ответа API."""
    response = get_checked(with_group_id(url, group_id), "API организаторов", transport)
    try:
        payload = response.json()
    except ValueError:
        raise DatasetError("API организаторов вернул неожиданный ответ") from None
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
