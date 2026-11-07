import json
from pathlib import Path

import pytest

from backend.app.contracts import Checklist, Criterion, Dialog, Turn

ROOT = Path(__file__).resolve().parents[3]


def make_turns(*pairs: tuple[str, str]) -> list[Turn]:
    return [Turn(index=i, timestamp=f"00:{i:02d}", speaker=s, text=t) for i, (s, t) in enumerate(pairs)]


def make_dialog(*pairs: tuple[str, str], cid: str = "t-1") -> Dialog:
    return Dialog(
        conversation_id=cid,
        dataset_group_id="TEST",
        channel="agent chat",
        language="RU",
        transcript=make_turns(*pairs),
    )


@pytest.fixture(scope="session")
def checklist() -> Checklist:
    data = json.loads((ROOT / "config/checklist.default.json").read_text(encoding="utf-8"))
    return Checklist(id="default", version=1, **data)


@pytest.fixture(scope="session")
def sample_dialogs() -> list[Dialog]:
    data = json.loads((ROOT / "config/sample_dialogs.json").read_text(encoding="utf-8"))
    return [
        Dialog(
            conversation_id=r["conversation_id"],
            dataset_group_id=data["dataset_group_id"],
            channel=r["channel"],
            language=r["language"],
            transcript=[Turn(index=i, **t) for i, t in enumerate(r["transcript"])],
            audio_url=r.get("audio_url"),
        )
        for r in data["records"]
    ]


@pytest.fixture
def dialog() -> Dialog:
    return make_dialog(
        ("client", "Как посмотреть комиссию?"),
        ("operator", "Здравствуйте! Меня зовут Мира. Откройте раздел «Отчёты»."),
        ("client", "Спасибо"),
    )


@pytest.fixture
def new_criterion_checklist(checklist: Checklist) -> Checklist:
    extra = Criterion(
        id="x99", title="Новый", description="Новый критерий без подсказки.", answer_type="yes_no", weight=5
    )
    return checklist.model_copy(update={"criteria": [*checklist.criteria, extra]})
