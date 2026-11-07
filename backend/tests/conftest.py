"""Общие объекты для тестов: чек-лист и диалог без обращения к сети и к файлам."""

import pytest

from backend.app.contracts import Checklist, Criterion, Dialog, ScaleStep, Section, Turn


def make_criterion(criterion_id: str, **overrides: object) -> Criterion:
    fields: dict[str, object] = {
        "id": criterion_id,
        "section_id": "s1",
        "title": f"Критерий {criterion_id}",
        "description": "Описание",
        "answer_type": "yes_no",
        "weight": 25,
    }
    return Criterion(**{**fields, **overrides})


@pytest.fixture
def checklist() -> Checklist:
    return Checklist(
        id="checklist-test",
        version=1,
        name="Тестовый чек-лист",
        sections=[Section(id="s1", title="Секция")],
        criteria=[
            make_criterion("yes-no"),
            make_criterion("optional", allow_na=True, na_condition="Неприменимо"),
            make_criterion(
                "scale",
                answer_type="scale",
                scale=[ScaleStep(value=10, label="Хорошо"), ScaleStep(value=0, label="Плохо")],
            ),
            make_criterion("flag", answer_type="flag", weight=0),
        ],
    )


@pytest.fixture
def dialog() -> Dialog:
    return Dialog(
        conversation_id="test-001",
        dataset_group_id="TEST",
        channel="agent chat",
        language="RU",
        transcript=[
            Turn(index=0, timestamp="00:00", speaker="client", text="Вопрос клиента"),
            Turn(index=1, timestamp="00:10", speaker="bot", text="Ответ бота"),
            Turn(index=2, timestamp="00:40", speaker="operator", text="Ответ оператора"),
        ],
    )
