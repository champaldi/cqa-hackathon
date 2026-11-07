import json
from pathlib import Path

import pytest

from backend.app.contracts import Checklist, Criterion, Dialog, ScaleStep, Turn

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
def default_checklist() -> Checklist:
    data = json.loads((ROOT / "config/checklist.default.json").read_text(encoding="utf-8"))
    return Checklist(id="default", version=1, **data)


@pytest.fixture(scope="session")
def fake_dialogs() -> list[Dialog]:
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
def simple_dialog() -> Dialog:
    return make_dialog(
        ("client", "Как посмотреть комиссию?"),
        ("operator", "Здравствуйте! Меня зовут Мира. Откройте раздел «Отчёты»."),
        ("client", "Спасибо"),
    )


NEW_SCALE_CRITERION = Criterion(
    id="x99",
    title="Новый шкальный критерий",
    description="Описание нового критерия без подсказки.",
    answer_type="scale",
    weight=5,
    scale=[ScaleStep(value=v, label=f"шаг {v} из шкалы") for v in range(6)],
)


@pytest.fixture
def new_criterion_checklist(default_checklist: Checklist) -> Checklist:
    """Чек-лист с добавленным критерием: новый id, шкала 0-5, без llm_hint."""
    return default_checklist.model_copy(
        update={"criteria": [*default_checklist.criteria, NEW_SCALE_CRITERION]}
    )
