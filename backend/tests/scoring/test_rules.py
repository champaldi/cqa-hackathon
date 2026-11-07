"""Правила подсчёта из docs/BRIEF.md на стартовом чек-листе config/checklist.default.json.

Ответы записаны строкой в порядке критериев c01–c08: «д» — да, «н» — нет, «na» — N/A,
число — ступень шкалы.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.contracts import (
    Appeal,
    Checklist,
    ChecklistDraft,
    Criterion,
    CriterionResult,
    Decision,
    Evidence,
    ScaleStep,
)
from backend.app.scoring.engine import apply_decisions, score
from backend.app.settings import ROOT_DIR

ALL_MAX = "д д д 20 д 10 д н"


def load_default() -> Checklist:
    raw = json.loads((ROOT_DIR / "config" / "checklist.default.json").read_text(encoding="utf-8"))
    draft = ChecklistDraft.model_validate(raw)
    return Checklist(**draft.model_dump(), id="t", version=1)


@pytest.fixture
def default() -> Checklist:
    return load_default()


def one(criterion_id: str, token: str) -> CriterionResult:
    if token == "д":
        return CriterionResult(criterion_id=criterion_id, answer="yes", explanation="Обоснование")
    if token == "н":
        return CriterionResult(criterion_id=criterion_id, answer="no", explanation="Обоснование")
    if token == "na":
        return CriterionResult(criterion_id=criterion_id, answer="na", explanation="Обоснование")
    return CriterionResult(
        criterion_id=criterion_id, answer="scale", scale_value=int(token), explanation="Обоснование"
    )


def answers(checklist: Checklist, line: str) -> list[CriterionResult]:
    tokens = line.split()
    assert len(tokens) == len(checklist.criteria)
    return [one(criterion.id, token) for criterion, token in zip(checklist.criteria, tokens, strict=True)]


def changed(criterion_id: str, answer: str, at: datetime | None = None, **extra: object) -> Appeal:
    decision = Decision(
        action="change",
        reason="Пересмотр",
        answer=answer,
        decided_at=at or datetime(2026, 1, 1, tzinfo=UTC),
        **extra,
    )
    return Appeal(
        id=f"ap-{criterion_id}-{answer}",
        evaluation_id="ev",
        criterion_id=criterion_id,
        comment="Не согласен",
        status="changed",
        decision=decision,
    )


# ---------- 13 контрольных примеров ----------

CASES = [
    (1, "д д д 20 д 10 д н", 100.00),
    (2, "н н н 0 н 0 н н", 0.00),
    (3, "н na д 15 д 7 д н", 77.06),
    (4, "д na na 10 н 4 na н", 43.33),
    (5, "д na na na д 7 na н", 88.75),
    (6, "д д д 20 д 7 д н", 95.50),
    (7, "д д д 20 д 4 д н", 91.00),
    (8, "д д д 20 д 0 д н", 85.00),
    (9, "н н д 20 н 0 na н", 42.11),
    (10, "н н na 0 н 7 н н", 13.13),
    (11, "д н na 0 н 7 н н", 25.63),
    (12, "д д д 20 д 10 д д", 100.00),
    (13, "н na д 15 д 7 д д", 77.06),
]


@pytest.mark.parametrize(("case", "line", "expected"), CASES, ids=[f"case-{c[0]}" for c in CASES])
def test_control_case_total(default: Checklist, case: int, line: str, expected: float) -> None:
    summary = score(default, answers(default, line))

    assert summary.total == expected


@pytest.mark.parametrize(("case", "line", "expected"), CASES, ids=[f"case-{c[0]}" for c in CASES])
def test_control_case_gross_error(default: Checklist, case: int, line: str, expected: float) -> None:
    summary = score(default, answers(default, line))

    flagged = line.split()[-1] == "д"
    assert summary.gross_error is flagged
    assert summary.gross_error_criteria == (["c08"] if flagged else [])


def test_half_is_rounded_up(default: Checklist) -> None:
    # 10,5 из 80 = 13,125: банковское округление и float дали бы 13,12
    assert score(default, answers(default, "н н na 0 н 7 н н")).total == 13.13


def test_case_3_sections_use_redistributed_weights(default: Checklist) -> None:
    summary = score(default, answers(default, "н na д 15 д 7 д н"))

    sections = {s.section_id: (s.points, s.max_points) for s in summary.sections}
    assert [s.section_id for s in summary.sections] == ["s1", "s2", "s3", "s4"]
    assert sections == {
        "s1": (0, 11.76),
        "s2": (41.18, 47.06),
        "s3": (35.88, 41.18),
        "s4": (0, 0),
    }


def test_case_4_total_is_not_a_sum_of_rounded_sections(default: Checklist) -> None:
    summary = score(default, answers(default, "д na na 10 н 4 na н"))

    assert summary.total == 43.33


def test_criterion_rows_keep_exact_redistributed_values(default: Checklist) -> None:
    rows = {row.criterion_id: row for row in score(default, answers(default, "н na д 15 д 7 д н")).criteria}

    assert rows["c02"].applicable is False
    assert rows["c02"].effective_weight == 0
    assert rows["c02"].points == 0
    assert rows["c01"].base_weight == 10
    assert rows["c01"].effective_weight == pytest.approx(1000 / 85)
    assert rows["c04"].points == pytest.approx(15 * 100 / 85)
    assert rows["c08"].applicable is False


def test_effective_weights_of_applicable_criteria_add_up_to_100(default: Checklist) -> None:
    rows = score(default, answers(default, "д na na 10 н 4 na н")).criteria

    assert sum(row.effective_weight for row in rows) == pytest.approx(100)


# ---------- Апелляции ----------


def test_appeal_a_identification_no_to_na(default: Checklist) -> None:
    results = answers(default, "д д н 20 д 10 д н")
    assert score(default, results).total == 80.00

    final = apply_decisions(results, [changed("c03", "na")])

    assert score(default, final).total == 100.00


def test_appeal_b_identification_na_to_no(default: Checklist) -> None:
    results = answers(default, "д д na 20 д 10 д н")
    assert score(default, results).total == 100.00

    final = apply_decisions(results, [changed("c03", "no")])

    assert score(default, final).total == 80.00


def test_appeal_c_contact_yes_to_no(default: Checklist) -> None:
    results = answers(default, "д na д 15 д 7 д н")
    assert score(default, results).total == 88.82

    final = apply_decisions(results, [changed("c01", "no")])

    assert score(default, final).total == 77.06


def test_appeal_d_gross_error_removed(default: Checklist) -> None:
    results = answers(default, "д д д 20 д 10 д д")
    before = score(default, results)
    assert (before.total, before.gross_error) == (100.00, True)

    after = score(default, apply_decisions(results, [changed("c08", "no")]))

    assert (after.total, after.gross_error, after.gross_error_criteria) == (100.00, False, [])


def test_latest_changed_decision_wins_regardless_of_order(default: Checklist) -> None:
    results = answers(default, ALL_MAX)
    early = changed("c04", "scale", datetime(2026, 1, 1, tzinfo=UTC), scale_value=5)
    late = changed("c04", "scale", datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=1), scale_value=15)

    for appeals in ([early, late], [late, early]):
        final = {r.criterion_id: r for r in apply_decisions(results, appeals)}
        assert final["c04"].scale_value == 15


def test_open_and_confirmed_appeals_keep_answers(default: Checklist) -> None:
    results = answers(default, ALL_MAX)
    opened = Appeal(id="ap-1", evaluation_id="ev", criterion_id="c01", comment="Не согласен")
    confirmed = Appeal(
        id="ap-2",
        evaluation_id="ev",
        criterion_id="c05",
        comment="Не согласен",
        status="confirmed",
        decision=Decision(action="confirm", reason="Верно"),
    )

    assert apply_decisions(results, [opened, confirmed]) == results


def test_changed_status_without_decision_is_ignored(default: Checklist) -> None:
    results = answers(default, ALL_MAX)
    broken = Appeal(id="ap-1", evaluation_id="ev", criterion_id="c01", comment="x", status="changed")

    assert apply_decisions(results, [broken]) == results


def test_decision_reason_goes_to_explanation_and_evidence_stays() -> None:
    evidence = [Evidence(kind="quote", turn_index=2, quote="Синтетическая реплика")]
    results = [CriterionResult(criterion_id="c01", answer="yes", explanation="Было", evidence=evidence)]
    appeal = changed("c01", "no").model_copy(
        update={"decision": Decision(action="change", reason="Не представился", answer="no")}
    )

    final = apply_decisions(results, [appeal])

    assert final[0].explanation == "Изменено проверяющим: Не представился"
    assert final[0].evidence == evidence


def test_scale_value_is_cleared_for_non_scale_answer(default: Checklist) -> None:
    results = answers(default, ALL_MAX)

    final = {r.criterion_id: r for r in apply_decisions(results, [changed("c04", "na")])}

    assert final["c04"].answer == "na"
    assert final["c04"].scale_value is None


def test_original_results_are_not_mutated(default: Checklist) -> None:
    results = answers(default, ALL_MAX)
    snapshot = [r.model_copy() for r in results]

    apply_decisions(results, [changed("c01", "no"), changed("c04", "scale", scale_value=0)])

    assert results == snapshot


# ---------- Отдельный чек-лист без применимых критериев ----------


@pytest.fixture
def tiny() -> Checklist:
    return Checklist(
        id="tiny",
        version=1,
        name="Синтетический",
        criteria=[
            Criterion(
                id="k1",
                title="К1",
                description="Да/нет",
                answer_type="yes_no",
                weight=60,
                allow_na=True,
                na_condition="Неприменимо",
            ),
            Criterion(
                id="k2",
                title="К2",
                description="Шкала",
                answer_type="scale",
                weight=40,
                allow_na=True,
                na_condition="Неприменимо",
                scale=[ScaleStep(value=v, label=str(v)) for v in range(11)],
            ),
            Criterion(id="f", title="Флаг", description="Флаг", answer_type="flag", weight=0),
        ],
    )


def test_all_na_gives_no_total(tiny: Checklist) -> None:
    summary = score(tiny, answers(tiny, "na na н"))

    assert summary.total is None
    assert summary.gross_error is False


def test_all_na_with_gross_error_keeps_flag(tiny: Checklist) -> None:
    summary = score(tiny, answers(tiny, "na na д"))

    assert summary.total is None
    assert summary.gross_error is True
    assert summary.gross_error_criteria == ["f"]


def test_applicable_with_zero_points_gives_zero_not_none(tiny: Checklist) -> None:
    assert score(tiny, answers(tiny, "н 0 н")).total == 0.0


# ---------- Замена критерия: веса не зашиты в код ----------


@pytest.fixture
def replaced(default: Checklist) -> Checklist:
    c09 = Criterion(
        id="c09",
        section_id="s1",
        title="Новый критерий",
        description="Да — синтетическое условие выполнено.",
        answer_type="yes_no",
        weight=15,
    )
    criteria = [c09 if c.id == "c01" else c for c in default.criteria]
    return default.model_copy(update={"id": "t2", "version": 2, "criteria": criteria})


def test_replaced_criterion_sum_105_is_normalized(replaced: Checklist) -> None:
    assert sum(c.weight for c in replaced.criteria) == 105
    assert score(replaced, answers(replaced, "н д д 20 д 10 д н")).total == 85.71


def test_replaced_criterion_all_max_is_100(replaced: Checklist) -> None:
    assert score(replaced, answers(replaced, ALL_MAX)).total == 100.00


def test_sections_without_scored_members_are_empty(default: Checklist) -> None:
    summary = score(default, answers(default, ALL_MAX))

    s4 = next(s for s in summary.sections if s.section_id == "s4")
    assert (s4.title, s4.points, s4.max_points) == ("Грубые нарушения", 0, 0)


# ---------- Ошибки входа ----------


def test_missing_result_raises(default: Checklist) -> None:
    with pytest.raises(ValueError, match="c08"):
        score(default, answers(default, ALL_MAX)[:-1])


def test_unknown_criterion_raises(default: Checklist) -> None:
    results = [*answers(default, ALL_MAX), one("zz", "д")]

    with pytest.raises(ValueError, match="zz"):
        score(default, results)


def test_duplicate_result_raises(default: Checklist) -> None:
    results = [*answers(default, ALL_MAX), one("c01", "н")]

    with pytest.raises(ValueError, match="c01"):
        score(default, results)


def test_scale_answer_without_value_raises(default: Checklist) -> None:
    results = [
        CriterionResult(criterion_id="c04", answer="scale", explanation="Без ступени")
        if r.criterion_id == "c04"
        else r
        for r in answers(default, ALL_MAX)
    ]

    with pytest.raises(ValueError, match="c04"):
        score(default, results)
