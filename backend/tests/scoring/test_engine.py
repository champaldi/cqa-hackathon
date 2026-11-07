"""Тесты заглушки подсчёта: только форма результата и явные решения.

Формулы с перераспределением N/A и округлением добавляет задача qa/scoring-engine.
"""

from backend.app.contracts import Appeal, Checklist, CriterionResult, Decision
from backend.app.scoring.engine import apply_decisions, score


def result(criterion_id: str, answer: str = "yes", scale_value: int | None = None) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion_id, answer=answer, scale_value=scale_value, explanation="Обоснование"
    )


def all_yes(checklist: Checklist) -> list[CriterionResult]:
    return [
        result("yes-no"),
        result("optional"),
        result("scale", "scale", 10),
        result("flag", "no"),
    ]


def appeal(criterion_id: str, decision: Decision | None) -> Appeal:
    status = "open" if decision is None else "changed" if decision.action == "change" else "confirmed"
    return Appeal(
        id=f"appeal-{criterion_id}",
        evaluation_id="ev",
        criterion_id=criterion_id,
        comment="Не согласен",
        status=status,
        decision=decision,
    )


def test_summary_has_a_row_for_every_criterion(checklist: Checklist) -> None:
    summary = score(checklist, all_yes(checklist))

    assert [row.criterion_id for row in summary.criteria] == [c.id for c in checklist.criteria]


def test_summary_has_a_row_for_every_section(checklist: Checklist) -> None:
    summary = score(checklist, all_yes(checklist))

    assert [section.section_id for section in summary.sections] == ["s1"]


def test_criterion_with_na_is_not_applicable(checklist: Checklist) -> None:
    results = [result("optional", "na") if r.criterion_id == "optional" else r for r in all_yes(checklist)]

    rows = {row.criterion_id: row for row in score(checklist, results).criteria}

    assert rows["optional"].applicable is False
    assert rows["yes-no"].applicable is True


def test_criterion_without_weight_is_not_applicable(checklist: Checklist) -> None:
    rows = {row.criterion_id: row for row in score(checklist, all_yes(checklist)).criteria}

    assert rows["flag"].applicable is False


def test_total_is_empty_without_applicable_criteria(checklist: Checklist) -> None:
    results = [result(c.id, "na") for c in checklist.criteria]

    assert score(checklist, results).total is None


def test_gross_error_is_reported_separately_from_points(checklist: Checklist) -> None:
    clean = score(checklist, all_yes(checklist))
    results = [result("flag", "yes") if r.criterion_id == "flag" else r for r in all_yes(checklist)]

    flagged = score(checklist, results)

    assert flagged.gross_error is True
    assert flagged.gross_error_criteria == ["flag"]
    assert flagged.total == clean.total


def test_criterion_without_result_is_not_applicable(checklist: Checklist) -> None:
    rows = {row.criterion_id: row for row in score(checklist, [result("yes-no")]).criteria}

    assert rows["scale"].applicable is False


def test_changed_decision_replaces_the_answer(checklist: Checklist) -> None:
    decision = Decision(action="change", reason="Цитата не подтверждает", answer="no")

    final = apply_decisions(all_yes(checklist), [appeal("yes-no", decision)])

    assert final[0].answer == "no"
    assert "Цитата не подтверждает" in final[0].explanation


def test_changed_decision_can_set_a_scale_value(checklist: Checklist) -> None:
    decision = Decision(action="change", reason="Ниже", answer="scale", scale_value=0)

    final = apply_decisions(all_yes(checklist), [appeal("scale", decision)])

    assert final[2].scale_value == 0


def test_confirmed_and_open_appeals_keep_the_answer(checklist: Checklist) -> None:
    results = all_yes(checklist)
    confirmed = Decision(action="confirm", reason="Верно")

    final = apply_decisions(results, [appeal("yes-no", confirmed), appeal("scale", None)])

    assert final == results


def test_original_results_stay_unchanged(checklist: Checklist) -> None:
    results = all_yes(checklist)
    decision = Decision(action="change", reason="Иначе", answer="no")

    apply_decisions(results, [appeal("yes-no", decision)])

    assert results[0].answer == "yes"
