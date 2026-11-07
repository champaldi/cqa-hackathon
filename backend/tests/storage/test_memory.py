from datetime import UTC, datetime, timedelta

import pytest

from backend.app.contracts import Appeal, BatchJob, Checklist, Dialog, Evaluation, ScoreSummary
from backend.app.storage.memory import MemoryStorage


def make_evaluation(evaluation_id: str, created_at: datetime | None = None) -> Evaluation:
    return Evaluation(
        id=evaluation_id,
        conversation_id="test-001",
        checklist_id="checklist-test",
        results=[],
        score=ScoreSummary(total=None, criteria=[]),
        created_at=created_at or datetime.now(UTC),
    )


def make_appeal(appeal_id: str, evaluation_id: str = "ev-1", status: str = "open") -> Appeal:
    return Appeal(
        id=appeal_id, evaluation_id=evaluation_id, criterion_id="yes-no", comment="Не согласен", status=status
    )


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def test_dialog_can_be_read_after_saving(storage: MemoryStorage, dialog: Dialog) -> None:
    storage.save_dialogs([dialog])

    assert storage.get_dialog(dialog.conversation_id) == dialog


def test_saving_same_dialog_replaces_it(storage: MemoryStorage, dialog: Dialog) -> None:
    storage.save_dialogs([dialog])
    storage.save_dialogs([dialog.model_copy(update={"language": "EN"})])

    assert [saved.language for saved in storage.list_dialogs()] == ["EN"]


def test_dialogs_can_be_filtered_by_group(storage: MemoryStorage, dialog: Dialog) -> None:
    other = dialog.model_copy(update={"conversation_id": "other", "dataset_group_id": "OTHER"})
    storage.save_dialogs([dialog, other])

    assert [saved.conversation_id for saved in storage.list_dialogs("OTHER")] == ["other"]


def test_missing_records_are_none(storage: MemoryStorage) -> None:
    assert storage.get_dialog("x") is None
    assert storage.get_checklist("x") is None
    assert storage.get_evaluation("x") is None
    assert storage.latest_evaluation("x") is None
    assert storage.get_appeal("x") is None
    assert storage.get_job("x") is None


def test_checklists_are_listed_by_version(storage: MemoryStorage, checklist: Checklist) -> None:
    storage.save_checklist(checklist.model_copy(update={"id": "v2", "version": 2}))
    storage.save_checklist(checklist)

    assert [saved.version for saved in storage.list_checklists()] == [1, 2]


def test_saved_evaluation_cannot_be_overwritten(storage: MemoryStorage) -> None:
    storage.save_evaluation(make_evaluation("ev-1"))

    with pytest.raises(ValueError, match="ev-1"):
        storage.save_evaluation(make_evaluation("ev-1"))


def test_latest_evaluation_is_the_newest_one(storage: MemoryStorage) -> None:
    now = datetime.now(UTC)
    storage.save_evaluation(make_evaluation("new", now))
    storage.save_evaluation(make_evaluation("old", now - timedelta(minutes=1)))

    latest = storage.latest_evaluation("test-001")

    assert latest is not None and latest.id == "new"


def test_appeals_can_be_filtered(storage: MemoryStorage) -> None:
    storage.save_appeal(make_appeal("a1"))
    storage.save_appeal(make_appeal("a2", evaluation_id="ev-2"))
    storage.save_appeal(make_appeal("a3", status="confirmed"))

    assert [a.id for a in storage.list_appeals(evaluation_id="ev-2")] == ["a2"]
    assert [a.id for a in storage.list_appeals(status="open")] == ["a1", "a2"]


def test_saving_appeal_updates_its_status(storage: MemoryStorage) -> None:
    appeal = storage.save_appeal(make_appeal("a1"))
    storage.save_appeal(appeal.model_copy(update={"status": "confirmed"}))

    saved = storage.get_appeal("a1")

    assert saved is not None and saved.status == "confirmed"


def test_job_can_be_updated(storage: MemoryStorage) -> None:
    job = storage.save_job(BatchJob(id="job", group_id="DEV", checklist_id="c"))
    storage.save_job(job.model_copy(update={"status": "done"}))

    saved = storage.get_job("job")

    assert saved is not None and saved.status == "done"
