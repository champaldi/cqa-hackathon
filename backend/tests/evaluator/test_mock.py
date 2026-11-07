import json
from pathlib import Path

import pytest

from backend.app.contracts import Checklist, Dialog, Turn
from backend.app.datasets.normalize import normalize_dataset
from backend.app.evaluator.mock import MockEvaluator

SAMPLE_PATH = Path(__file__).parents[3] / "config" / "sample_dialogs.json"


@pytest.fixture
def sample_dialogs() -> list[Dialog]:
    return normalize_dataset(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))


def test_every_criterion_gets_a_result(dialog: Dialog, checklist: Checklist) -> None:
    output = MockEvaluator().evaluate(dialog, checklist)

    assert [r.criterion_id for r in output.results] == [c.id for c in checklist.criteria]


def test_same_input_gives_same_output(dialog: Dialog, checklist: Checklist) -> None:
    evaluator = MockEvaluator()

    assert evaluator.evaluate(dialog, checklist) == evaluator.evaluate(dialog, checklist)


def test_usage_shows_a_free_mock_run(dialog: Dialog, checklist: Checklist) -> None:
    usage = MockEvaluator().evaluate(dialog, checklist).usage

    assert usage.model == "mock"
    assert usage.llm_calls == 0
    assert usage.cost_usd == 0


def test_answers_respect_the_criterion_settings(sample_dialogs: list[Dialog], checklist: Checklist) -> None:
    criteria = {c.id: c for c in checklist.criteria}

    for dialog in sample_dialogs:
        for result in MockEvaluator().evaluate(dialog, checklist).results:
            criterion = criteria[result.criterion_id]
            if result.answer == "na":
                assert criterion.allow_na
            elif criterion.answer_type == "scale":
                assert result.answer == "scale"
                assert result.scale_value in {step.value for step in criterion.scale or []}
            else:
                assert result.answer in {"yes", "no"}


def test_quotes_come_from_the_referenced_turn(sample_dialogs: list[Dialog], checklist: Checklist) -> None:
    for dialog in sample_dialogs:
        for result in MockEvaluator().evaluate(dialog, checklist).results:
            for evidence in result.evidence:
                if evidence.kind == "quote":
                    turn = dialog.transcript[evidence.turn_index]
                    assert turn.speaker == "operator"
                    assert evidence.quote in turn.text


def test_every_result_has_explanation_and_evidence(
    sample_dialogs: list[Dialog], checklist: Checklist
) -> None:
    for dialog in sample_dialogs:
        for result in MockEvaluator().evaluate(dialog, checklist).results:
            assert result.explanation
            assert result.evidence


def test_new_criterion_works_without_code_changes(dialog: Dialog, checklist: Checklist) -> None:
    extended = checklist.model_copy(
        update={"criteria": [*checklist.criteria, checklist.criteria[0].model_copy(update={"id": "new"})]}
    )

    output = MockEvaluator().evaluate(dialog, extended)

    assert output.results[-1].criterion_id == "new"


def test_dialog_without_operator_is_handled(dialog: Dialog, checklist: Checklist) -> None:
    only_client = dialog.model_copy(
        update={"transcript": [Turn(index=0, timestamp="00:00", speaker="client", text="Есть кто?")]}
    )

    results = MockEvaluator().evaluate(only_client, checklist).results

    assert all(e.kind != "quote" for r in results for e in r.evidence)


def test_empty_transcript_is_handled(dialog: Dialog, checklist: Checklist) -> None:
    empty = dialog.model_copy(update={"transcript": []})

    assert len(MockEvaluator().evaluate(empty, checklist).results) == len(checklist.criteria)
