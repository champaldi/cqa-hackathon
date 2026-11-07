"""Приводит раздел data из API организаторов к модели Dialog. Исходные метки времени не меняются."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from backend.app.contracts import Dialog, Turn
from backend.app.datasets.timing import with_timing
from backend.app.errors import DatasetError


def normalize_dataset(payload: Mapping[str, Any]) -> list[Dialog]:
    group_id = payload.get("dataset_group_id")
    records = payload.get("records")
    if not isinstance(group_id, str) or not group_id or not isinstance(records, list):
        raise DatasetError("В наборе нет dataset_group_id или списка records")
    return [_normalize_record(record, group_id) for record in records]


def _normalize_record(record: Any, group_id: str) -> Dialog:
    conversation_id = record.get("conversation_id") if isinstance(record, dict) else None
    try:
        dialog = Dialog(
            conversation_id=record["conversation_id"],
            dataset_group_id=group_id,
            channel=record["channel"],
            language=record["language"],
            transcript=[
                Turn.model_validate({**turn, "index": index})
                for index, turn in enumerate(record["transcript"])
            ],
            audio_url=record.get("audio_url") or None,
        )
    except (KeyError, TypeError, ValidationError):
        raise DatasetError(f"Запись {conversation_id or 'без id'}: неверный формат") from None
    return with_timing(dialog)
