"""Сравнение с эталоном на синтетических данных: без реальных диалогов, без сети и без модели."""

import json

import pytest

from backend.app.contracts import Checklist, ChecklistDraft, CriterionResult, Evaluation
from backend.app.scoring.engine import score
from backend.app.settings import ROOT_DIR
from eval.compare import (
    ANSWER,
    MISSING,
    NA_FALSE,
    NA_MISSED,
    SCALE_STEP,
    Answer,
    classify,
    compare,
    load_gold,
    load_model,
    main,
    parse_answer,
    render,
    to_json,
)

IDS = ["c01", "c02", "c03", "c04", "c05", "c06", "c07", "c08"]
ALL_MAX = "yes yes yes 20 yes 10 yes no"


@pytest.fixture
def checklist() -> Checklist:
    raw = json.loads((ROOT_DIR / "config" / "checklist.default.json").read_text(encoding="utf-8"))
    return Checklist(**ChecklistDraft.model_validate(raw).model_dump(), id="checklist-v1", version=1)


def tokens(line: str) -> dict[str, object]:
    return {crit: int(t) if t.isdigit() else t for crit, t in zip(IDS, line.split(), strict=True)}


def gold_entry(
    cid: str, line: str, language: str = "RU", channel: str = "agent chat", **extra: object
) -> dict:
    return {
        "conversation_id": cid,
        "language": language,
        "channel": channel,
        "criteria": tokens(line),
        **extra,
    }


def card(cid: str, line: str, checklist: Checklist, drop: str | None = None) -> dict:
    results = []
    for crit, value in tokens(line).items():
        if crit == drop:
            continue
        if isinstance(value, int):
            results.append(
                CriterionResult(criterion_id=crit, answer="scale", scale_value=value, explanation="x")
            )
        else:
            results.append(CriterionResult(criterion_id=crit, answer=value, explanation="x"))
    # Итог считаем как будто пропавший критерий N/A: score() требует результат по каждому критерию
    summary = score(checklist, results if drop is None else [*results, _na(drop)])
    evaluation = Evaluation(
        id=f"ev-{cid}", conversation_id=cid, checklist_id=checklist.id, results=results, score=summary
    )
    return {"evaluation": evaluation.model_dump(mode="json"), "checklist": checklist.model_dump(mode="json")}


def _na(crit: str) -> CriterionResult:
    return CriterionResult(criterion_id=crit, answer="na", explanation="x")


def run(gold: list[dict], cards: list[dict]):
    return compare(load_gold({"dialogs": gold}), load_model(cards))


# ---------- Разбор и виды расхождений ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("yes", Answer("yes")),
        ("Да", Answer("yes")),
        ("N/A", Answer("na")),
        (15, Answer("scale", 15)),
        ({"answer": "no", "doubtful": True}, Answer("no")),
        ({"answer": "scale", "scale_value": 7}, Answer("scale", 7)),
    ],
)
def test_parse_answer(raw: object, expected: Answer) -> None:
    assert parse_answer(raw, "t") == expected


@pytest.mark.parametrize("raw", ["maybe", True, -5, None])
def test_parse_answer_rejects_garbage(raw: object) -> None:
    with pytest.raises(ValueError):
        parse_answer(raw, "t")


@pytest.mark.parametrize(
    ("gold", "model", "kind"),
    [
        (Answer("yes"), Answer("no"), ANSWER),
        (Answer("na"), Answer("yes"), NA_MISSED),
        (Answer("no"), Answer("na"), NA_FALSE),
        (Answer("scale", 20), Answer("scale", 15), SCALE_STEP),
        (Answer("yes"), None, MISSING),
    ],
)
def test_classify(gold: Answer, model: Answer | None, kind: str) -> None:
    assert classify(gold, model) == kind


def test_gold_rejects_duplicates_and_empty() -> None:
    with pytest.raises(ValueError, match="дважды"):
        load_gold({"dialogs": [gold_entry("d1", ALL_MAX), gold_entry("d1", ALL_MAX)]})
    with pytest.raises(ValueError, match="dialogs"):
        load_gold({"dialogs": []})


# ---------- Сравнение ----------


def test_full_match(checklist: Checklist) -> None:
    report = run([gold_entry("d1", ALL_MAX)], [card("d1", ALL_MAX, checklist)])

    assert (report.overall.match, report.overall.total, report.overall.rate) == (8, 8, 100.0)
    assert report.totals == [{"conversation_id": "d1", "gold": 100.0, "model": 100.0, "diff": 0.0}]
    assert (report.gross.match, report.gross.total) == (1, 1)
    assert report.kinds == {}


def test_one_mismatch_yes_no(checklist: Checklist) -> None:
    report = run([gold_entry("d1", ALL_MAX)], [card("d1", "no yes yes 20 yes 10 yes no", checklist)])

    assert (report.overall.match, report.overall.total) == (7, 8)
    assert report.kinds == {ANSWER: 1}
    assert report.by_criterion["c01"].rate == 0.0
    assert report.totals[0]["diff"] == -10.0


def test_na_and_scale_mismatches(checklist: Checklist) -> None:
    report = run(
        [gold_entry("d1", "yes na yes 20 yes 10 yes no")],
        [card("d1", "yes yes na 15 yes 10 yes no", checklist)],
    )

    assert report.kinds == {NA_MISSED: 1, NA_FALSE: 1, SCALE_STEP: 1}
    kinds = {row.criterion_id: row.kind for row in report.rows}
    assert (kinds["c02"], kinds["c03"], kinds["c04"]) == (NA_MISSED, NA_FALSE, SCALE_STEP)


def test_missing_criterion_result(checklist: Checklist) -> None:
    report = run([gold_entry("d1", ALL_MAX)], [card("d1", ALL_MAX, checklist, drop="c05")])

    assert report.kinds == {MISSING: 1}
    assert next(r for r in report.rows if r.criterion_id == "c05").model is None


def test_doubtful_is_counted_separately(checklist: Checklist) -> None:
    gold = gold_entry("d1", ALL_MAX)
    gold["criteria"]["c03"] = {"answer": "na", "doubtful": True}
    gold["doubtful_criteria"] = ["c07"]
    report = run([gold], [card("d1", "yes yes yes 20 yes 10 no no", checklist)])

    assert (report.overall.match, report.overall.total) == (6, 6)
    assert (report.doubtful.match, report.doubtful.total) == (0, 2)
    assert "[спорный]" in render(report)


def test_dialog_level_doubtful_marks_every_criterion(checklist: Checklist) -> None:
    report = run([gold_entry("d1", ALL_MAX, doubtful=True)], [card("d1", ALL_MAX, checklist)])

    assert report.overall.total == 0
    assert report.doubtful.total == 8


def test_languages_and_channels(checklist: Checklist) -> None:
    gold = [
        gold_entry("ru", ALL_MAX, "RU"),
        gold_entry("en", ALL_MAX, "EN"),
        gold_entry("kz", ALL_MAX, "KZ"),
        gold_entry("call", ALL_MAX, "RU", "voice call"),
    ]
    cards = [
        card("ru", ALL_MAX, checklist),
        card("en", ALL_MAX, checklist),
        card("kz", "yes yes yes 10 no 10 yes no", checklist),
        card("call", ALL_MAX, checklist),
    ]
    report = run(gold, cards)

    assert {k: v.rate for k, v in report.by_language.items()} == {"RU": 100.0, "EN": 100.0, "KZ": 75.0}
    assert report.by_channel["voice call"].rate == 100.0
    assert report.by_channel["agent chat"].total == 24


def test_unmatched_ids(checklist: Checklist) -> None:
    report = run(
        [gold_entry("d1", ALL_MAX), gold_entry("d2", ALL_MAX)],
        [card("d1", ALL_MAX, checklist), card("other", ALL_MAX, checklist)],
    )

    assert report.missing_dialogs == ["d2"]
    assert report.overall.total == 8


def test_gross_error_mismatch(checklist: Checklist) -> None:
    report = run([gold_entry("d1", "yes yes yes 20 yes 10 yes yes")], [card("d1", ALL_MAX, checklist)])

    assert (report.gross.match, report.gross.total) == (0, 1)
    assert report.totals[0]["diff"] == 0.0  # грубая ошибка на итог не влияет


def test_gold_total_uses_scoring_engine(checklist: Checklist) -> None:
    report = run([gold_entry("d1", "no na yes 15 yes 7 yes no")], [card("d1", ALL_MAX, checklist)])

    assert report.totals[0]["gold"] == 77.06


def test_report_json_and_text(checklist: Checklist) -> None:
    report = run([gold_entry("d1", ALL_MAX)], [card("d1", "no yes yes 20 yes 10 yes no", checklist)])

    data = to_json(report)
    assert data["overall"]["rate"] == 87.5
    assert data["by_criterion"]["c01"]["rate"] == 0.0
    text = render(report)
    assert "7/8 (87.5%)" in text
    assert "d1 c01: yes → no" in text


def test_cli_with_saved_model(tmp_path, checklist: Checklist, capsys) -> None:
    gold_file = tmp_path / "gold.json"
    model_file = tmp_path / "model.json"
    report_file = tmp_path / "report.json"
    gold_file.write_text(json.dumps({"dialogs": [gold_entry("d1", ALL_MAX)]}), encoding="utf-8")
    model_file.write_text(json.dumps([card("d1", ALL_MAX, checklist)]), encoding="utf-8")

    assert main(["--gold", str(gold_file), "--model", str(model_file), "--json", str(report_file)]) == 0

    assert "8/8 (100.0%)" in capsys.readouterr().out
    assert json.loads(report_file.read_text(encoding="utf-8"))["overall"]["match"] == 8


def test_checklist_mismatch_is_reported(checklist: Checklist) -> None:
    replaced = [c.model_copy(update={"id": "c09"}) if c.id == "c01" else c for c in checklist.criteria]
    other = checklist.model_copy(update={"id": "checklist-v2", "version": 2, "criteria": replaced})
    model_card = card("d1", ALL_MAX, checklist)
    model_card["checklist"] = other.model_dump(mode="json")

    report = run([gold_entry("d1", ALL_MAX)], [model_card])

    assert report.checklist_mismatch == ["d1"]
    assert "не совпадают с эталоном у d1" in render(report)


def test_kz_check_and_seen_model_are_reported(checklist: Checklist) -> None:
    gold = [
        gold_entry("kz1", ALL_MAX, "KZ", kz_checked_by="Карим, переводчик"),
        gold_entry("kz2", ALL_MAX, "KZ"),
        gold_entry("ru1", ALL_MAX, "RU", seen_model_before_labeling=True),
    ]
    report = run(gold, [card(cid, ALL_MAX, checklist) for cid in ("kz1", "kz2", "ru1")])

    assert report.kz_checked == {"kz1": "Карим, переводчик", "kz2": None}
    assert report.seen_model == ["ru1"]
    text = render(report)
    assert "Казахская разметка проверена: 1/2" in text
    assert "не проверены: kz2" in text
    assert "Разметка не слепая (разметчик видел ответы модели): 1 — ru1" in text
