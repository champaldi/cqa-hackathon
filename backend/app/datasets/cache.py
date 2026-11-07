"""Локальная копия наборов: импорт переживает сбой API организаторов.

Файлы лежат в data/ и не попадают в git: в них настоящие диалоги и подписанные ссылки.
Имя файла безопасно, потому что group_id проверяет ImportRequest.
"""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _path(directory: Path, group_id: str) -> Path:
    return directory / f"{group_id}.json"


def read_group(directory: Path | None, group_id: str) -> dict[str, Any] | None:
    if directory is None:
        return None
    try:
        payload = json.loads(_path(directory, group_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Кеш набора %s не прочитан: %s", group_id, type(exc).__name__)
        return None
    return payload if isinstance(payload, dict) else None


def write_group(directory: Path | None, group_id: str, payload: Mapping[str, Any]) -> None:
    """Сбой записи не мешает импорту: данные уже получены."""
    if directory is None:
        return
    path = _path(directory, group_id)
    temporary = path.with_suffix(".tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        logger.warning("Кеш набора %s не записан: %s", group_id, type(exc).__name__)
