import json
from pathlib import Path

import pytest

from backend.app.datasets.normalize import normalize_dataset
from backend.app.errors import DatasetError

SAMPLE_PATH = Path(__file__).parents[3] / "config" / "sample_dialogs.json"


def raw_record(**overrides: object) -> dict:
    record = {
        "conversation_id": "raw-001",
        "channel": "agent chat",
        "language": "EN",
        "transcript": [
            {"timestamp": "00:02", "speaker": "client", "text": "Hi"},
            {"timestamp": "00:09", "speaker": "operator", "text": "Hello"},
        ],
        "audio_url": None,
    }
    return {**record, **overrides}


def test_turns_receive_sequential_indexes() -> None:
    [dialog] = normalize_dataset({"dataset_group_id": "DEV", "records": [raw_record()]})

    assert [turn.index for turn in dialog.transcript] == [0, 1]


def test_original_timestamps_are_preserved() -> None:
    [dialog] = normalize_dataset({"dataset_group_id": "DEV", "records": [raw_record()]})

    assert [turn.timestamp for turn in dialog.transcript] == ["00:02", "00:09"]


def test_group_id_is_copied_to_every_dialog() -> None:
    dialogs = normalize_dataset({"dataset_group_id": "CONTROL", "records": [raw_record()]})

    assert dialogs[0].dataset_group_id == "CONTROL"


def test_invalid_record_is_reported_by_conversation_id() -> None:
    payload = {"dataset_group_id": "DEV", "records": [raw_record(language="DE")]}

    with pytest.raises(DatasetError, match="raw-001"):
        normalize_dataset(payload)


def test_record_without_transcript_is_rejected() -> None:
    record = raw_record()
    del record["transcript"]

    with pytest.raises(DatasetError, match="raw-001"):
        normalize_dataset({"dataset_group_id": "DEV", "records": [record]})


@pytest.mark.parametrize("payload", [{}, {"dataset_group_id": "DEV"}, {"records": []}, {"records": "x"}])
def test_payload_without_required_fields_is_rejected(payload: dict) -> None:
    with pytest.raises(DatasetError):
        normalize_dataset(payload)


def test_repository_sample_matches_the_organizers_format() -> None:
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

    dialogs = normalize_dataset(payload)

    assert {dialog.language for dialog in dialogs} == {"RU", "KZ", "EN"}
    assert {dialog.channel for dialog in dialogs} == {"agent chat", "voice call"}
